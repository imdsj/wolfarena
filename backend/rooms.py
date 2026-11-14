"""Thread-safe in-memory rooms and viewer-scoped WebSocket state."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import logging
from math import ceil
from secrets import compare_digest, token_urlsafe
from threading import RLock
from time import time
from typing import Literal

from .actions import (
    ActionUnavailableError,
    available_actions_for_state,
    execute_engine_action,
)
from .ai_controller import AIController, AIControllerResult
from .ai_growth import L1RulePolicy
from .player_agent import PlayerAgent, build_agents
from .tactic_policy import DirectivePolicy, load_validated_directives
from .win_probability import baseline_timeline, predict_win_rate
from .game_engine import (
    Event,
    EventType,
    GameState,
    Phase,
    Player,
    Role,
    SPECTATOR_VIEW,
    Visibility,
    append_event,
    close_self_destruct_window,
    create_game,
    get_player,
    get_witch_kill_target,
    get_visible_events,
    timeout_last_words,
    timeout_public_speech,
)
from .schemas import (
    ActionRequest,
    AgentInsight,
    CreatedRoomResponse,
    DecisionTraceView,
    JoinedRoomResponse,
    PublicEvent,
    PublicPlayer,
    RoomSnapshot,
    ViewerIdentity,
)

logger = logging.getLogger(__name__)

# Host-only transitions the server now performs on its own. They stay legal
# at the engine/API level (the AI controller and tests use them) but are not
# offered as buttons, so a human host never has to click the game forward.
SYSTEM_ONLY_ACTIONS = frozenset(
    {
        "begin_day",
        "resolve_night",
        "resolve_vote",
        "begin_banishment_last_words",
        "close_self_destruct_window",
        "close_vote",
    }
)


class RoomNotFoundError(LookupError):
    """Raised when a room does not exist."""


class InvalidPlayerTokenError(PermissionError):
    """Raised when a player credential is missing or invalid."""


class InvalidSpectatorPasswordError(PermissionError):
    """Raised when a spectator password is invalid."""


class RoomFullError(RuntimeError):
    """Raised when another human cannot join the room."""


class DuplicateNicknameError(ValueError):
    """Raised when a nickname is already used in the game."""


class SeatUnavailableError(ValueError):
    """Raised when a requested seat is out of range or already occupied."""


class JoinClosedError(RuntimeError):
    """Raised when a room no longer accepts new players."""


class RoomPermissionError(PermissionError):
    """Raised when a viewer cannot perform an action."""


class OutOfPhaseError(RuntimeError):
    """Raised when an action is invalid for the current game phase."""


class UnsupportedActionError(ValueError):
    """Raised when the action name is not implemented."""


# 系统推进类动作在定时器已经自动推进后会“迟到”。此时把它当作已完成，
# 返回当前快照即可，避免给前端弹出无意义的“动作已失效”。
SUPERSEDED_TRANSITION_PHASES: dict[str, frozenset[Phase]] = {
    "begin_day": frozenset(
        {
            Phase.DAY_LAST_WORDS,
            Phase.DAY_DISCUSSION,
            Phase.SELF_DESTRUCT,
            Phase.VOTE,
            Phase.DAY_HUNTER_SHOT,
            Phase.END,
        }
    ),
    "resolve_night": frozenset(
        {
            Phase.NIGHT_HUNTER_SHOT,
            Phase.DAY_ANNOUNCEMENT,
            Phase.DAY_LAST_WORDS,
            Phase.DAY_DISCUSSION,
            Phase.SELF_DESTRUCT,
            Phase.VOTE,
            Phase.DAY_HUNTER_SHOT,
            Phase.END,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class ViewerAccess:
    """Authenticated identity used to filter room events."""

    room_id: str
    kind: Literal["player", "spectator"]
    player_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """An authenticated viewer and the snapshot visible at login time."""

    room: "Room"
    access: ViewerAccess
    snapshot: RoomSnapshot


@dataclass(frozen=True, slots=True)
class RoomMutation:
    """A committed room change and the event range it produced."""

    room: "Room"
    previous_event_seq: int
    current_event_seq: int


@dataclass(frozen=True, slots=True)
class AIActionContext:
    """The only game information a model is allowed to receive."""

    room: "Room"
    access: ViewerAccess
    snapshot: RoomSnapshot
    legal_actions: tuple[str, ...]
    valid_target_ids: tuple[str, ...]


@dataclass(slots=True)
class Room:
    """One game, its credentials, and its serialization lock."""

    room_id: str
    state: GameState
    max_humans: int
    reserved_human_count: int
    spectator_password: str
    host_player_id: str = "p1"
    claimed_player_ids: set[str] = field(default_factory=set)
    tokens_by_player: dict[str, str] = field(default_factory=dict)
    player_by_token: dict[str, str] = field(default_factory=dict)
    continue_gate: bool = False
    continue_acks: set[str] = field(default_factory=set)
    lock: RLock = field(default_factory=RLock, repr=False)
    ai_policy: L1RulePolicy = field(init=False, repr=False)
    agents: dict[str, PlayerAgent] = field(init=False, repr=False)
    win_rate_predictions: dict[int, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            cards = load_validated_directives()
        except Exception:
            cards = ()
        self.ai_policy = DirectivePolicy(seed=self.state.seed, cards=cards)
        self.agents = build_agents(self.state, cards)

    @property
    def human_count(self) -> int:
        return len(self.claimed_player_ids)

    @property
    def last_event_seq(self) -> int:
        return self.state.events[-1].event_seq if self.state.events else -1

    def claim_player(self, player_id: str) -> str:
        """Create and remember a credential for one player."""

        token = token_urlsafe(32)
        self.claimed_player_ids.add(player_id)
        self.tokens_by_player[player_id] = token
        self.player_by_token[token] = player_id
        return token

    def player_for_token(self, token: str | None) -> Player:
        if not token:
            raise InvalidPlayerTokenError("缺少玩家凭证")
        player_id = self.player_by_token.get(token)
        if player_id is None:
            raise InvalidPlayerTokenError("玩家凭证无效")
        return get_player(self.state, player_id)

    def choose_join_seat(self) -> Player:
        """Choose a reserved human seat first, then convert an AI seat."""

        if self.human_count >= self.max_humans:
            raise RoomFullError("房间真人已满")

        unclaimed = [
            player
            for player in self.state.players
            if player.player_id not in self.claimed_player_ids
        ]
        reserved = [
            player
            for player in unclaimed
            if player.seat <= self.reserved_human_count
        ]
        return min(reserved or unclaimed, key=lambda player: player.seat)

    def rename_player(self, player: Player, nickname: str) -> None:
        if any(
            other.player_id != player.player_id and other.name == nickname
            for other in self.state.players
        ):
            raise DuplicateNicknameError("昵称已被使用")
        player.name = nickname
        player.is_human = True
        self.agents.pop(player.player_id, None)


class InMemoryRoomRepository:
    """Room store that serializes mutations per room."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._registry_lock = RLock()
        self.ai_controller = AIController(self)

    def create_room(
        self,
        *,
        seed: int,
        human_count: int,
        max_humans: int,
        nickname: str,
    ) -> CreatedRoomResponse:
        if human_count > max_humans:
            raise ValueError("human_count 不能大于 max_humans")

        names = [nickname] + [f"玩家{seat}" for seat in range(2, 10)]
        if len(set(names)) != len(names):
            raise DuplicateNicknameError("昵称与默认玩家名称冲突")

        with self._registry_lock:
            room_id = self._new_room_id()
            state = create_game(
                seed=seed,
                human_count=human_count,
                player_names=names,
            )
            room = Room(
                room_id=room_id,
                state=state,
                max_humans=max_humans,
                reserved_human_count=human_count,
                spectator_password=token_urlsafe(12),
            )
            creator = get_player(state, "p1")
            token = room.claim_player(creator.player_id)
            self._rooms[room_id] = room
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=creator.player_id,
            )
            return CreatedRoomResponse(
                room_id=room_id,
                player_token=token,
                spectator_password=room.spectator_password,
                room=self.snapshot_for_access(room, access),
            )

    def join_room(
        self,
        room_id: str,
        nickname: str,
        *,
        seat: int | None = None,
    ) -> tuple[JoinedRoomResponse, RoomMutation]:
        room = self._get_room(room_id)
        with room.lock:
            if room.state.phase is not Phase.INIT:
                raise JoinClosedError("游戏开始后不能加入新玩家")

            previous_event_seq = room.last_event_seq
            if seat is None:
                player = room.choose_join_seat()
            else:
                player = self._seat_player(room, seat)
            room.rename_player(player, nickname)
            token = room.claim_player(player.player_id)
            append_event(
                room.state,
                EventType.PLAYER_JOINED,
                target_id=player.player_id,
                visibility=Visibility.PUBLIC,
                data={
                    "seat": player.seat,
                    "name": player.name,
                },
            )
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=player.player_id,
            )
            response = JoinedRoomResponse(
                player_token=token,
                room=self.snapshot_for_access(room, access),
            )
            mutation = RoomMutation(
                room=room,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )
            return response, mutation

    @staticmethod
    def _seat_player(room: "Room", seat: int) -> Player:
        player = next(
            (
                candidate
                for candidate in room.state.players
                if candidate.seat == seat
            ),
            None,
        )
        if player is None or player.player_id in room.claimed_player_ids:
            raise SeatUnavailableError(f"{seat} 号座位不可用")
        return player

    def authenticate_player(
        self,
        room_id: str,
        token: str | None,
    ) -> AuthenticatedSession:
        room = self._get_room(room_id)
        with room.lock:
            player = room.player_for_token(token)
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=player.player_id,
            )
            return AuthenticatedSession(
                room=room,
                access=access,
                snapshot=self.snapshot_for_access(room, access),
            )

    def authenticate_spectator(
        self,
        room_id: str,
        password: str | None,
    ) -> AuthenticatedSession:
        room = self._get_room(room_id)
        with room.lock:
            if (
                not password
                or not compare_digest(password, room.spectator_password)
            ):
                raise InvalidSpectatorPasswordError("观战密码错误")
            access = ViewerAccess(room_id=room_id, kind="spectator")
            return AuthenticatedSession(
                room=room,
                access=access,
                snapshot=self.snapshot_for_access(room, access),
            )

    def get_snapshot(self, room_id: str, token: str | None) -> RoomSnapshot:
        room = self._get_room(room_id)
        with room.lock:
            player = room.player_for_token(token)
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=player.player_id,
            )
            return self.snapshot_for_access(room, access)

    def win_rate_prediction(
        self,
        access: ViewerAccess,
        event_seq: int,
    ) -> dict:
        """Return a cached public-information prediction for a spectator."""

        if access.kind != "spectator":
            raise RoomPermissionError("胜率预测只在上帝视角开放")
        room = self._get_room(access.room_id)
        with room.lock:
            cached = room.win_rate_predictions.get(event_seq)
            if cached is not None:
                return deepcopy(cached)
            state = deepcopy(room.state)
        prediction = predict_win_rate(state, event_seq)
        with room.lock:
            room.win_rate_predictions[event_seq] = prediction
            return deepcopy(prediction)

    def available_seats(self, room_id: str) -> list[int]:
        room = self._get_room(room_id)
        with room.lock:
            return sorted(
                player.seat
                for player in room.state.players
                if player.player_id not in room.claimed_player_ids
            )

    def ai_action_context(self, access: ViewerAccess) -> AIActionContext:
        room = self._get_room(access.room_id)
        with room.lock:
            if access.kind != "player" or access.player_id is None:
                raise RoomPermissionError("观战者不能调用 AI 行动")
            player = self._access_player(room, access)
            snapshot = self.snapshot_for_access(room, access)
            legal_actions = tuple(
                action.action for action in snapshot.available_actions
            )
            valid_target_ids = tuple(
                dict.fromkeys(
                    target_id
                    for action in snapshot.available_actions
                    for target_id in action.target_ids
                )
            )
            return AIActionContext(
                room=room,
                access=access,
                snapshot=snapshot,
                legal_actions=legal_actions,
                valid_target_ids=valid_target_ids,
            )

    def execute_action(
        self,
        access: ViewerAccess,
        request: ActionRequest,
        *,
        now: float | None = None,
    ) -> RoomMutation:
        room = self._get_room(access.room_id)
        with room.lock:
            if access.kind != "player":
                raise RoomPermissionError("观战者不能执行游戏动作")
            player = self._access_player(room, access)
            if (
                request.action == "start_night"
                and room.human_count < room.reserved_human_count
            ):
                raise ValueError("还有真人未加入，不能开始游戏")
            superseded = SUPERSEDED_TRANSITION_PHASES.get(request.action)
            if (
                superseded is not None
                and player.player_id == room.host_player_id
                and room.state.phase in superseded
            ):
                previous_event_seq = room.last_event_seq
                return RoomMutation(
                    room=room,
                    previous_event_seq=previous_event_seq,
                    current_event_seq=room.last_event_seq,
                )
            state_before = deepcopy(room.state)
            previous_event_seq = room.last_event_seq
            try:
                execute_engine_action(
                    room.state,
                    player,
                    request,
                    host_player_id=room.host_player_id,
                    now=now,
                )
            except Exception:
                room.state = state_before
                raise
            vote_resolved_now = any(
                event.event_type is EventType.VOTE_RESULT
                for event in room.state.events[previous_event_seq + 1 :]
            )
            if vote_resolved_now:
                # Freeze right after the vote result, even on a tie that
                # already advanced the phase, so humans can read the board.
                room.continue_gate = True
                room.continue_acks.clear()
            if request.action == "last_words":
                # Freeze again after last words so nobody misses them.
                room.continue_gate = True
                room.continue_acks.clear()
            return RoomMutation(
                room=room,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )

    def execute_action_and_advance_ai(
        self,
        access: ViewerAccess,
        request: ActionRequest,
        *,
        now: float | None = None,
    ) -> RoomMutation:
        room = self._get_room(access.room_id)
        with room.lock:
            mutation = self.execute_action(access, request, now=now)
            if request.action in {"speech", "last_words"}:
                # Publish the human's own words immediately instead of
                # blocking the response while eight AI speeches are prepared.
                reference = time() if now is None else now
                room.state.phase_deadline_at = reference + 0.2
                room.state.phase_deadline_kind = "phase_pace"
                return RoomMutation(
                    room=mutation.room,
                    previous_event_seq=mutation.previous_event_seq,
                    current_event_seq=mutation.current_event_seq,
                )
            controller_result = self.advance_ai(access.room_id, now=now)
            return RoomMutation(
                room=mutation.room,
                previous_event_seq=mutation.previous_event_seq,
                current_event_seq=controller_result.current_event_seq,
            )

    def advance_ai(
        self,
        room_id: str,
        *,
        now: float | None = None,
    ) -> AIControllerResult:
        room = self._get_room(room_id)
        if room.continue_gate:
            return AIControllerResult(
                steps=0,
                stopped_reason="human_turn",
                previous_event_seq=room.last_event_seq,
                current_event_seq=room.last_event_seq,
            )
        return self.ai_controller.advance(room_id, now=now)

    def request_continue(
        self,
        room_id: str,
        access: "ViewerAccess",
        *,
        now: float | None = None,
    ) -> RoomMutation:
        """Acknowledge the post-vote freeze for one player.

        The game only moves on once every living human has acknowledged, so
        one impatient player can no longer skip the others.
        """

        room = self._get_room(room_id)
        with room.lock:
            if access.kind != "player":
                raise RoomPermissionError("观战者不能推进流程")
            player = self._access_player(room, access)
            previous_event_seq = room.last_event_seq
            if not room.continue_gate:
                return RoomMutation(
                    room=room,
                    previous_event_seq=previous_event_seq,
                    current_event_seq=room.last_event_seq,
                )
            room.continue_acks.add(player.player_id)
            living_humans = [
                candidate
                for candidate in room.state.players
                if candidate.is_alive
                and candidate.is_human
                and candidate.player_id in room.claimed_player_ids
            ]
            if all(
                candidate.player_id in room.continue_acks
                for candidate in living_humans
            ):
                room.continue_gate = False
                room.continue_acks.clear()
                room.state.phase_deadline_at = None
                room.state.phase_deadline_kind = None
                self.advance_ai(room_id, now=now)
            return RoomMutation(
                room=room,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )

    def auto_play_human_turn(
        self,
        room_id: str,
        *,
        now: float,
    ) -> None:
        """Play one action for an idle human so the game can continue."""

        room = self._get_room(room_id)
        with room.lock:
            step = self.ai_controller.plan_next_step(
                room.state,
                policy=room.ai_policy,
                now=now,
                include_human=True,
            )
            if step is None:
                return
            actor_id = (
                step.actor.player_id
                if step.actor is not None
                else room.host_player_id
            )
            request = step.request
            if request.action == "vote":
                # The rules count an uncast ballot as abstention, so an idle
                # human is replaced with a neutral abstain instead of a vote
                # the AI would invent for them.
                request = ActionRequest(action="vote", target_id=None)
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=actor_id,
            )
            state_before = deepcopy(room.state)
            try:
                self.execute_action(access, request, now=now)
            except Exception:
                room.state = state_before
                logger.exception(
                    "Human auto-play failed for %s action=%s",
                    room_id,
                    request.action,
                )
                return
            self.advance_ai(room_id, now=now)

    def process_expired_deadlines(
        self,
        now: float,
    ) -> tuple[RoomMutation, ...]:
        with self._registry_lock:
            room_ids = tuple(self._rooms)

        mutations: list[RoomMutation] = []
        for room_id in room_ids:
            room = self._get_room(room_id)
            with room.lock:
                if room.continue_gate:
                    if not any(
                        player.is_human and player.is_alive
                        for player in room.state.players
                    ):
                        # No living human left to acknowledge the pause, so
                        # the AI-only remainder of the game plays itself out.
                        room.continue_gate = False
                        room.continue_acks.clear()
                        room.state.phase_deadline_at = None
                        room.state.phase_deadline_kind = None
                        self.advance_ai(room_id, now=now)
                    continue
                timeout_kind = self._expired_timeout_kind(room.state, now)
                if timeout_kind is None:
                    continue
                previous_event_seq = room.last_event_seq
                state_before = deepcopy(room.state)
                try:
                    if timeout_kind == "human_action":
                        self.auto_play_human_turn(room_id, now=now)
                    elif timeout_kind == "phase_pace":
                        pass  # advanced below by advance_ai()
                    elif timeout_kind == "last_words":
                        timeout_last_words(room.state, now)
                    elif timeout_kind == "speech":
                        timeout_public_speech(room.state, now)
                    else:
                        close_self_destruct_window(room.state, now=now)
                except Exception:
                    room.state = state_before
                    logger.exception(
                        "Room timer action failed for %s at %s",
                        room_id,
                        now,
                    )
                    continue

                if timeout_kind != "human_action":
                    self.advance_ai(room_id, now=now)
                if room.last_event_seq > previous_event_seq:
                    mutations.append(
                        RoomMutation(
                            room=room,
                            previous_event_seq=previous_event_seq,
                            current_event_seq=room.last_event_seq,
                        )
                    )
        return tuple(mutations)

    @staticmethod
    def _expired_timeout_kind(
        state: GameState,
        now: float,
    ) -> str | None:
        active_deadline = InMemoryRoomRepository._active_deadline(state)
        if active_deadline is None:
            return None
        deadline_kind, deadline_at = active_deadline
        return deadline_kind if now >= deadline_at else None

    @staticmethod
    def _active_deadline(
        state: GameState,
    ) -> tuple[str, float] | None:
        """Return the one server deadline that currently governs the phase."""

        if state.phase_deadline_at is not None:
            return (state.phase_deadline_kind or "human_action", state.phase_deadline_at)
        day_result = state.day_result
        if day_result is None:
            return None
        if (
            state.phase is Phase.DAY_LAST_WORDS
            and day_result.last_words_deadline is not None
        ):
            return ("last_words", day_result.last_words_deadline)
        if (
            state.phase is Phase.DAY_DISCUSSION
            and day_result.speech_deadline is not None
        ):
            return ("speech", day_result.speech_deadline)
        if (
            state.phase is Phase.SELF_DESTRUCT
            and day_result.self_destruct_deadline is not None
        ):
            return ("self_destruct", day_result.self_destruct_deadline)
        return None

    def start_night(
        self,
        access: ViewerAccess,
        *,
        captain_id: str | None = None,
    ) -> RoomMutation:
        if captain_id is not None:
            raise ValueError("统一动作路由暂不支持手动指定狼队长")
        try:
            return self.execute_action(
                access,
                ActionRequest(action="start_night"),
            )
        except ActionUnavailableError as error:
            raise OutOfPhaseError(str(error)) from error

    def record_ai_fallback(
        self,
        access: ViewerAccess,
        *,
        reason: str,
        action: str,
    ) -> RoomMutation:
        room = self._get_room(access.room_id)
        with room.lock:
            player = self._access_player(room, access)
            previous_event_seq = room.last_event_seq
            append_event(
                room.state,
                EventType.AI_FALLBACK_USED,
                actor_id=player.player_id,
                visibility=Visibility.PLAYER,
                visible_to=(player.player_id,),
                data={
                    "reason": reason[:120],
                    "fallback_action": action[:64],
                },
            )
            return RoomMutation(
                room=room,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )

    def record_ai_rejection(
        self,
        access: ViewerAccess,
        *,
        reason: str,
        candidate_action: str,
        candidate_target_id: str | None,
    ) -> RoomMutation:
        room = self._get_room(access.room_id)
        with room.lock:
            player = self._access_player(room, access)
            previous_event_seq = room.last_event_seq
            append_event(
                room.state,
                EventType.AI_ACTION_REJECTED,
                actor_id=player.player_id,
                target_id=candidate_target_id,
                visibility=Visibility.PLAYER,
                visible_to=(player.player_id,),
                data={
                    "reason": reason[:120],
                    "candidate_action": candidate_action[:64],
                },
            )
            return RoomMutation(
                room=room,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )

    def visible_events_since(
        self,
        room: Room,
        access: ViewerAccess,
        after_event_seq: int,
    ) -> tuple[Event, ...]:
        with room.lock:
            viewer = self._event_viewer(room, access)
            return tuple(
                event
                for event in get_visible_events(room.state, viewer)
                if event.event_seq > after_event_seq
            )

    @staticmethod
    def _last_night_summary(state: GameState) -> str | None:
        """A stable, front-and-center line about the previous night."""

        if state.phase in {
            Phase.INIT,
            Phase.NIGHT_WOLF_DISCUSSION_R1,
            Phase.NIGHT_WOLF_DISCUSSION_R2,
            Phase.NIGHT_WOLF_KILL,
            Phase.NIGHT_SEER_CHECK,
            Phase.NIGHT_WITCH_ACTION,
            Phase.NIGHT_RESOLUTION,
            Phase.NIGHT_HUNTER_SHOT,
        }:
            return None
        day_result = state.day_result
        if day_result is None:
            return None
        day = state.day or 1
        if day_result.announced_death_ids:
            cause_labels = {
                "wolf_kill": "狼人击杀",
                "poisoned": "女巫毒杀",
                "hunter_shot": "猎人开枪",
                "banished": "投票放逐",
                "self_destruct": "自爆",
            }
            parts: list[str] = []
            for player in sorted(state.players, key=lambda item: item.seat):
                if player.player_id not in day_result.announced_death_ids:
                    continue
                causes = day_result.death_causes.get(player.player_id) or []
                labels = [
                    cause_labels.get(cause, cause) for cause in causes
                ]
                suffix = f"（{'、'.join(labels)}）" if labels else ""
                parts.append(f"{player.seat} 号{suffix}")
            return f"第 {day} 天 · 昨晚 {'、'.join(parts)} 出局"
        return f"第 {day} 天 · 昨晚是平安夜"

    @staticmethod
    def _announcements(state: GameState, access: ViewerAccess) -> list[str]:
        """Narrator lines plus the viewer's own role prompts, never hidden roles."""

        lines: list[str] = []
        phase = state.phase
        night = state.night_result
        day_result = state.day_result

        night_phases = {
            Phase.NIGHT_WOLF_DISCUSSION_R1,
            Phase.NIGHT_WOLF_DISCUSSION_R2,
            Phase.NIGHT_WOLF_KILL,
            Phase.NIGHT_SEER_CHECK,
            Phase.NIGHT_WITCH_ACTION,
            Phase.NIGHT_HUNTER_SHOT,
            Phase.NIGHT_RESOLUTION,
        }
        if phase is Phase.INIT:
            lines.append("等待房主开始夜晚。")
        elif phase in night_phases:
            lines.append("天黑请闭眼，夜间行动进行中。")
        elif phase is Phase.DAY_ANNOUNCEMENT:
            if day_result is not None and day_result.announced_death_ids:
                names = "、".join(
                    f"{player.seat} 号"
                    for player in state.players
                    if player.player_id in day_result.announced_death_ids
                )
                lines.append(f"天亮了，昨晚 {names} 被淘汰。")
            else:
                lines.append("天亮了，昨晚是平安夜。")
        elif phase is Phase.DAY_LAST_WORDS:
            lines.append("进入遗言环节。")
        elif phase is Phase.DAY_DISCUSSION:
            lines.append("进入自由发言环节，请依次发言。")
        elif phase is Phase.VOTE:
            lines.append("进入投票环节，请投票选出狼人，也可以弃权。")
        elif phase is Phase.DAY_HUNTER_SHOT:
            lines.append("猎人请选择是否开枪。")
        elif phase is Phase.END:
            lines.append("对局结束。")

        if access.kind == "player" and access.player_id is not None:
            player = get_player(state, access.player_id)
            role = player.role
            if (
                role is Role.SEER
                and night is not None
                and night.seer_target_id is not None
            ):
                target = get_player(state, night.seer_target_id)
                team = "狼人" if night.seer_result == "wolf" else "好人"
                lines.append(f"查验结果：{target.seat} 号是{team}。")
            if (
                role is Role.WITCH
                and phase is Phase.NIGHT_WITCH_ACTION
            ):
                items = []
                if state.antidote_available:
                    items.append("解药可用")
                if state.poison_available:
                    items.append("毒药可用")
                if items:
                    lines.append("你（女巫）还有：" + "、".join(items) + "。")
            if role is Role.HUNTER:
                if (
                    phase is Phase.NIGHT_HUNTER_SHOT
                    and night is not None
                    and night.hunter_can_shoot
                ):
                    lines.append("你（猎人）夜间可以开枪。")
                if (
                    phase is Phase.DAY_HUNTER_SHOT
                    and day_result is not None
                    and day_result.day_hunter_can_shoot
                ):
                    lines.append("你（猎人）白天可以开枪。")
        return lines

    def snapshot_for_access(
        self,
        room: Room,
        access: ViewerAccess,
        *,
        now: float | None = None,
    ) -> RoomSnapshot:
        with room.lock:
            server_time = time() if now is None else now
            active_deadline = self._active_deadline(room.state)
            deadline_kind = (
                active_deadline[0] if active_deadline is not None else None
            )
            deadline_at = (
                active_deadline[1] if active_deadline is not None else None
            )
            remaining_ms = (
                max(0, ceil((deadline_at - server_time) * 1000))
                if deadline_at is not None
                else None
            )
            viewer = self._event_viewer(room, access)
            visible_events = get_visible_events(room.state, viewer)
            witch_kill_target_visible = False
            witch_kill_target_id: str | None = None
            if access.kind == "spectator":
                viewer_identity = ViewerIdentity(
                    kind="spectator",
                    player_id=None,
                    seat=None,
                    name="观战者",
                    role=None,
                    is_alive=None,
                    is_host=False,
                )
            else:
                player = self._access_player(room, access)
                if (
                    player.role is Role.WITCH
                    and player.is_alive
                    and room.state.phase is Phase.NIGHT_WITCH_ACTION
                    and room.state.antidote_available
                ):
                    witch_kill_target_visible = True
                    witch_kill_target_id = get_witch_kill_target(
                        room.state,
                        player.player_id,
                    )
                viewer_identity = ViewerIdentity(
                    kind="player",
                    player_id=player.player_id,
                    seat=player.seat,
                    name=player.name,
                    role=player.role.value,
                    is_alive=player.is_alive,
                    is_host=player.player_id == room.host_player_id,
                )

            show_agent_insights = (
                access.kind == "spectator"
                or room.state.phase is Phase.END
            )
            agent_insights: list[AgentInsight] = []
            if show_agent_insights:
                agent_insights = [
                    self._agent_insight(room, agent)
                    for agent in sorted(
                        room.agents.values(),
                        key=lambda item: item.player_id,
                    )
                ]

            return RoomSnapshot(
                room_id=room.room_id,
                phase=room.state.phase.value,
                day=room.state.day,
                server_time=server_time,
                deadline_at=deadline_at,
                deadline_kind=deadline_kind,
                remaining_ms=remaining_ms,
                witch_kill_target_visible=witch_kill_target_visible,
                witch_kill_target_id=witch_kill_target_id,
                human_count=room.human_count,
                max_humans=room.max_humans,
                viewer=viewer_identity,
                players=[
                    PublicPlayer(
                        player_id=player.player_id,
                        seat=player.seat,
                        name=player.name,
                        is_human=player.player_id in room.claimed_player_ids,
                        is_alive=player.is_alive,
                        archetype=(
                            room.agents[player.player_id].persona.value
                            if player.player_id in room.agents
                            else None
                        ),
                    )
                    for player in sorted(
                        room.state.players,
                        key=lambda item: item.seat,
                    )
                ],
                visible_events=[
                    self.serialize_event(event)
                    for event in visible_events
                ],
                available_seats=[
                    player.seat
                    for player in room.state.players
                    if player.player_id not in room.claimed_player_ids
                ],
                announcements=self._announcements(room.state, access),
                last_night_summary=self._last_night_summary(room.state),
                awaiting_continue=(
                    room.continue_gate
                    and access.kind == "player"
                    and access.player_id is not None
                    and access.player_id not in room.continue_acks
                ),
                available_actions=(
                    []
                    if room.continue_gate
                    else list(
                        action
                        for action in available_actions_for_state(
                            room.state,
                            viewer,
                            host_player_id=room.host_player_id,
                            now=server_time,
                        )
                        if action.action not in SYSTEM_ONLY_ACTIONS
                    )
                ),
                agent_insights=agent_insights,
                win_rate_timeline=(
                    baseline_timeline(room.state)
                    if access.kind == "spectator"
                    else []
                ),
                win_rate_predictions=(
                    [
                        deepcopy(room.win_rate_predictions[key])
                        for key in sorted(room.win_rate_predictions)
                    ]
                    if access.kind == "spectator"
                    else []
                ),
            )

    @staticmethod
    def _agent_insight(room: "Room", agent: PlayerAgent) -> AgentInsight:
        player = get_player(room.state, agent.player_id)
        return AgentInsight(
            player_id=agent.player_id,
            seat=player.seat,
            name=player.name,
            archetype=agent.persona.value,
            current_plan=agent.current_plan,
            decision_traces=[
                DecisionTraceView(**trace.as_dict())
                for trace in agent.decision_traces
            ],
        )

    @staticmethod
    def serialize_event(event: Event) -> PublicEvent:
        return PublicEvent(
            event_seq=event.event_seq,
            event_type=event.event_type.value,
            day=event.day,
            phase=event.phase.value,
            actor_id=event.actor_id,
            target_id=event.target_id,
            visibility=event.visibility.value,
            data=dict(event.data),
        )

    def _event_viewer(self, room: Room, access: ViewerAccess) -> Player | str:
        if access.kind == "spectator":
            return SPECTATOR_VIEW
        return self._access_player(room, access)

    @staticmethod
    def _access_player(room: Room, access: ViewerAccess) -> Player:
        if access.player_id is None:
            raise InvalidPlayerTokenError("缺少玩家身份")
        try:
            return get_player(room.state, access.player_id)
        except KeyError as error:
            raise InvalidPlayerTokenError("玩家不属于当前房间") from error

    def _get_room(self, room_id: str) -> Room:
        with self._registry_lock:
            try:
                return self._rooms[room_id]
            except KeyError as error:
                raise RoomNotFoundError("房间不存在") from error

    def _new_room_id(self) -> str:
        while True:
            room_id = token_urlsafe(6)
            if room_id not in self._rooms:
                return room_id
