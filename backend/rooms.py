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
from .ai_growth import L0Policy
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
    CreatedRoomResponse,
    JoinedRoomResponse,
    PublicEvent,
    PublicPlayer,
    RoomSnapshot,
    ViewerIdentity,
)

logger = logging.getLogger(__name__)


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


class JoinClosedError(RuntimeError):
    """Raised when a room no longer accepts new players."""


class RoomPermissionError(PermissionError):
    """Raised when a viewer cannot perform an action."""


class OutOfPhaseError(RuntimeError):
    """Raised when an action is invalid for the current game phase."""


class UnsupportedActionError(ValueError):
    """Raised when the action name is not implemented."""


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
    lock: RLock = field(default_factory=RLock, repr=False)
    ai_policy: L0Policy = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.ai_policy = L0Policy(seed=self.state.seed)

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
    ) -> tuple[JoinedRoomResponse, RoomMutation]:
        room = self._get_room(room_id)
        with room.lock:
            if room.state.phase is not Phase.INIT:
                raise JoinClosedError("游戏开始后不能加入新玩家")

            previous_event_seq = room.last_event_seq
            player = room.choose_join_seat()
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
        return self.ai_controller.advance(room_id, now=now)

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
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=actor_id,
            )
            state_before = deepcopy(room.state)
            try:
                self.execute_action(access, step.request, now=now)
            except Exception:
                room.state = state_before
                logger.exception(
                    "Human auto-play failed for %s action=%s",
                    room_id,
                    step.request.action,
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
                timeout_kind = self._expired_timeout_kind(room.state, now)
                if timeout_kind is None:
                    continue
                previous_event_seq = room.last_event_seq
                state_before = deepcopy(room.state)
                try:
                    if timeout_kind == "human_action":
                        self.auto_play_human_turn(room_id, now=now)
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
                available_actions=list(
                    available_actions_for_state(
                        room.state,
                        viewer,
                        host_player_id=room.host_player_id,
                        now=server_time,
                    )
                ),
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
