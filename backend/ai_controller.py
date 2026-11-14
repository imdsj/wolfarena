"""Server-side AI turn driver built on the shared action router."""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from random import Random
from typing import TYPE_CHECKING, Literal

from .actions import available_actions_for_state
from .ai_growth import L1RulePolicy, speech_content
from .logic_audit import strongest_finding
from .speech_composer import (
    compose_speech,
    compose_speech_with_tools,
    llm_speech_enabled,
)
from .game_engine import (
    EventType,
    GameState,
    HUMAN_ACTION_TIMEOUT_SECONDS,
    NIGHT_PHASE_PACE_SECONDS,
    NIGHT_HUMAN_ACTION_TIMEOUT_SECONDS,
    Phase,
    Player,
    Role,
    Visibility,
    append_event,
    get_player,
)
from .schemas import ActionRequest, ActionView

if TYPE_CHECKING:
    from .rooms import RoomMutation


NIGHT_ACTION_PHASES = frozenset(
    {
        Phase.NIGHT_WOLF_DISCUSSION_R1,
        Phase.NIGHT_WOLF_DISCUSSION_R2,
        Phase.NIGHT_WOLF_KILL,
        Phase.NIGHT_SEER_CHECK,
        Phase.NIGHT_WITCH_ACTION,
        Phase.NIGHT_HUNTER_SHOT,
    }
)
HUMAN_TURN_TIMEOUT_PHASES = frozenset(
    NIGHT_ACTION_PHASES
    | {
        Phase.VOTE,
        Phase.DAY_HUNTER_SHOT,
    }
)
NIGHT_PACED_PHASES = frozenset(
    NIGHT_ACTION_PHASES
    | {
        Phase.NIGHT_RESOLUTION,
        Phase.DAY_ANNOUNCEMENT,
    }
)

# A real player is never replaced quickly: the room waits for their action
# instead of silently voting or acting for them. The long limit only exists
# so an abandoned seat cannot stall a room forever.
HUMAN_TURN_TIMEOUT_SECONDS = HUMAN_ACTION_TIMEOUT_SECONDS
VOTE_TURN_TIMEOUT_SECONDS = HUMAN_ACTION_TIMEOUT_SECONDS


@dataclass(frozen=True, slots=True)
class AIControllerResult:
    steps: int
    stopped_reason: Literal[
        "human_turn",
        "no_action",
        "step_limit",
        "action_failed",
        "phase_advanced",
        "phase_entered",
    ]
    previous_event_seq: int
    current_event_seq: int


@dataclass(frozen=True, slots=True)
class AIControllerStep:
    actor: Player | None
    request: ActionRequest
    is_system: bool = False


class AIController:
    """Advance local AI and system phases without bypassing action validation."""

    def __init__(self, repository, *, max_steps: int = 300) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps 必须大于 0")
        self._repository = repository
        self._max_steps = max_steps

    def advance(
        self,
        room_id: str,
        *,
        now: float | None = None,
    ) -> AIControllerResult:
        from .rooms import ViewerAccess

        room = self._repository._get_room(room_id)
        with room.lock:
            previous_event_seq = room.last_event_seq
            if room.continue_gate:
                return AIControllerResult(
                    steps=0,
                    stopped_reason="human_turn",
                    previous_event_seq=previous_event_seq,
                    current_event_seq=previous_event_seq,
                )
            self._clear_phase_deadline(room.state)
            start_phase = room.state.phase
            steps = 0
            reason: Literal[
                "human_turn",
                "no_action",
                "step_limit",
                "action_failed",
                "phase_advanced",
                "phase_entered",
            ] = "human_turn"
            while steps < self._max_steps:
                if room.continue_gate:
                    reason = "human_turn"
                    break
                if room.state.phase is Phase.END:
                    reason = "no_action"
                    break
                step = self.plan_next_step(
                    room.state,
                    policy=room.ai_policy,
                    agents=getattr(room, "agents", None),
                    now=now,
                    auto_close_vote=True,
                )
                if step is None:
                    reason = "human_turn"
                    break

                actor_id = step.actor.player_id if step.actor is not None else None
                access = ViewerAccess(
                    room_id=room_id,
                    kind="player",
                    player_id=actor_id or room.host_player_id,
                )
                state_before = deepcopy(room.state)
                context_before = self._context_key(room.state)
                try:
                    self._repository.execute_action(
                        access,
                        step.request,
                        now=now,
                    )
                except Exception as error:
                    room.state = state_before
                    self._record_failure(
                        room,
                        actor_id=actor_id,
                        action=step.request.action,
                        reason=self._failure_reason(error),
                    )
                    reason = "action_failed"
                    break

                steps += 1
                if self._context_key(room.state) == context_before:
                    room.state = state_before
                    self._record_failure(
                        room,
                        actor_id=actor_id,
                        action=step.request.action,
                        reason="AI动作未推进阶段或回合",
                    )
                    reason = "action_failed"
                    break
                now_phase = room.state.phase
                if start_phase in NIGHT_PACED_PHASES:
                    if now_phase is not start_phase:
                        reason = "phase_advanced"
                        break
                elif now_phase in NIGHT_PACED_PHASES:
                    reason = "phase_entered"
                    break
            else:
                reason = "step_limit"
                self._record_failure(
                    room,
                    actor_id=None,
                    action="step_limit",
                    reason=f"AI推进超过{self._max_steps}步",
                )

            if reason in {"human_turn", "phase_advanced", "phase_entered"}:
                self._ensure_phase_deadline(room.state, now)

            return AIControllerResult(
                steps=steps,
                stopped_reason=reason,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )

    def plan_next_step(
        self,
        state: GameState,
        *,
        policy,
        agents: dict | None = None,
        now: float | None,
        skip_optional_self_destruct: bool = True,
        auto_close_vote: bool = False,
        auto_start_game: bool = False,
        include_human: bool = False,
    ) -> AIControllerStep | None:
        if auto_start_game and state.phase is Phase.INIT:
            return AIControllerStep(
                actor=get_player(state, self._host_id(state)),
                request=ActionRequest(action="start_night"),
            )

        system_action = self._system_action(state, now=now)
        if system_action is not None:
            return AIControllerStep(
                actor=None,
                request=system_action,
                is_system=True,
            )

        if (
            auto_close_vote
            and state.phase is Phase.VOTE
            and state.day_result is not None
            and not state.day_result.votes_closed
            and all(
                player.player_id in state.day_result.votes
                for player in state.players
                if player.is_alive
            )
        ):
            return AIControllerStep(
                actor=None,
                request=ActionRequest(action="close_vote"),
                is_system=True,
            )

        actor = self._next_role_actor(state, include_human=include_human)
        if actor is None:
            return None
        if actor.is_human and not include_human:
            return None

        action_views = available_actions_for_state(
            state,
            actor,
            host_player_id=self._host_id(state),
            now=now,
        )
        if skip_optional_self_destruct:
            # Interactive L0 must finish the normal turn instead of selecting
            # an optional self-destruct and stalling the room for 10 seconds.
            non_stalling_views = tuple(
                view
                for view in action_views
                if view.action != "self_destruct"
            )
            if non_stalling_views:
                action_views = non_stalling_views
        if not action_views:
            return None
        observer = getattr(policy, "observe_state", None)
        if callable(observer):
            # Optional read-only hook for policies that learn from state.
            observer(state, actor)
        action = policy.choose_action(
            [view.action for view in action_views]
        )
        view = next(view for view in action_views if view.action == action)
        effective_policy = policy
        agent = None
        if agents is not None and not actor.is_human:
            candidate = agents.get(actor.player_id)
            if candidate is not None:
                agent = candidate
                effective_policy = candidate.policy
                action = effective_policy.choose_action(
                    [item.action for item in action_views]
                )
                view = next(
                    item for item in action_views if item.action == action
                )
        request, tool_calls = self._build_request_with_tools(
            state,
            actor,
            view,
            policy=effective_policy,
        )
        if agent is not None:
            tactic_ids = [
                tactic_id
                for call in tool_calls
                if isinstance(call, dict)
                for tactic_id in call.get("tactic_ids", ())
            ]
            agent.record(
                day=state.day,
                phase=state.phase.value,
                action=request.action,
                target_id=request.target_id,
                choice=request.choice,
                strategy_id=effective_policy.strategy_id,
                tool_calls=tool_calls,
                tactic_ids=tactic_ids,
            )
        return AIControllerStep(actor=actor, request=request)

    @staticmethod
    def _clear_phase_deadline(state: GameState) -> None:
        state.phase_deadline_at = None
        state.phase_deadline_kind = None

    def _ensure_phase_deadline(
        self,
        state: GameState,
        now: float | None,
    ) -> None:
        """Start the countdown for a human turn or a paced night phase."""

        reference = now if now is not None else time.time()
        actor = self._next_role_actor(state, include_human=True)
        if (
            state.phase in HUMAN_TURN_TIMEOUT_PHASES
            and actor is not None
            and actor.is_human
            and actor.is_alive
        ):
            # Wait for the real player. The timeout is intentionally long so
            # an unfinished human turn is never auto-played within a normal
            # game session.
            timeout = (
                VOTE_TURN_TIMEOUT_SECONDS
                if state.phase is Phase.VOTE
                else HUMAN_TURN_TIMEOUT_SECONDS
            )
            state.phase_deadline_at = reference + timeout
            state.phase_deadline_kind = "human_action"
            return
        elif state.phase in NIGHT_PACED_PHASES:
            state.phase_deadline_at = reference + NIGHT_PHASE_PACE_SECONDS
            state.phase_deadline_kind = "phase_pace"
        elif actor is not None and not actor.is_human:
            # An AI still owes this phase an action (e.g. the first daytime
            # speaker right after begin_day). Nudge the timer once so the
            # game can never sit idle with nobody scheduled to move.
            state.phase_deadline_at = reference + 0.1
            state.phase_deadline_kind = "phase_pace"
        else:
            self._clear_phase_deadline(state)

    @staticmethod
    def _system_action(
        state: GameState,
        *,
        now: float | None,
    ) -> ActionRequest | None:
        if state.phase is Phase.NIGHT_RESOLUTION:
            return ActionRequest(action="resolve_night")
        if state.phase is Phase.DAY_ANNOUNCEMENT:
            return ActionRequest(action="begin_day")
        if state.phase is Phase.VOTE and state.day_result is not None:
            if state.day_result.votes_closed and not state.day_result.vote_resolved:
                return ActionRequest(action="resolve_vote")
            if (
                state.day_result.vote_resolved
                and state.day_result.banishment_pending
            ):
                return ActionRequest(action="begin_banishment_last_words")
        if (
            state.phase is Phase.SELF_DESTRUCT
            and state.day_result is not None
            and state.day_result.self_destruct_deadline is not None
            and (time.time() if now is None else now)
            >= state.day_result.self_destruct_deadline
        ):
            return ActionRequest(action="close_self_destruct_window")
        return None

    def _next_role_actor(
        self,
        state: GameState,
        *,
        include_human: bool = False,
    ) -> Player | None:
        living = [
            player
            for player in sorted(state.players, key=lambda item: item.seat)
            if player.is_alive
        ]
        if state.phase is Phase.NIGHT_WOLF_DISCUSSION_R1:
            return _next_wolf_speaker(state, 1)
        if state.phase is Phase.NIGHT_WOLF_DISCUSSION_R2:
            return _next_wolf_speaker(state, 2)
        if state.phase is Phase.NIGHT_WOLF_KILL:
            if state.wolf_captain_id is None:
                return None
            return next(
                player
                for player in living
                if player.player_id == state.wolf_captain_id
            )
        if state.phase is Phase.NIGHT_SEER_CHECK:
            return next(
                (
                    player
                    for player in living
                    if player.role is Role.SEER
                ),
                None,
            )
        if state.phase is Phase.NIGHT_WITCH_ACTION:
            return next(
                (
                    player
                    for player in living
                    if player.role is Role.WITCH
                ),
                None,
            )
        if state.phase is Phase.NIGHT_HUNTER_SHOT:
            if state.night_result is None or not state.night_result.hunter_can_shoot:
                return None
            return next(
                (
                    player
                    for player in state.players
                    if player.role is Role.HUNTER
                ),
                None,
            )
        if state.phase is Phase.DAY_LAST_WORDS:
            if state.day_result is None or not state.day_result.last_words_queue:
                return None
            return next(
                (
                    player
                    for player in state.players
                    if player.player_id
                    == state.day_result.last_words_queue[0]
                ),
                None,
            )
        if state.phase is Phase.DAY_DISCUSSION:
            if state.day_result is None:
                return None
            index = state.day_result.next_speaker_index
            while (
                index < len(state.day_result.speech_order)
                and not next(
                    (
                        player.is_alive
                        for player in state.players
                        if player.player_id == state.day_result.speech_order[index]
                    ),
                    False,
                )
            ):
                index += 1
            if index >= len(state.day_result.speech_order):
                return None
            speaker_id = state.day_result.speech_order[index]
            return next(
                player
                for player in state.players
                if player.player_id == speaker_id
            )
        if state.phase is Phase.VOTE and state.day_result is not None:
            if state.day_result.votes_closed:
                return None
            return next(
                (
                    player
                    for player in living
                    if (not player.is_human or include_human)
                    and player.player_id not in state.day_result.votes
                ),
                None,
            )
        if state.phase is Phase.DAY_HUNTER_SHOT:
            if state.day_result is None or not state.day_result.day_hunter_can_shoot:
                return None
            return next(
                (
                    player
                    for player in state.players
                    if player.role is Role.HUNTER
                ),
                None,
            )
        return None

    def _build_request(
        self,
        state: GameState,
        actor: Player,
        view: ActionView,
        *,
        policy,
    ) -> ActionRequest:
        request, _ = self._build_request_with_tools(
            state,
            actor,
            view,
            policy=policy,
        )
        return request

    def _build_request_with_tools(
        self,
        state: GameState,
        actor: Player,
        view: ActionView,
        *,
        policy,
    ) -> tuple[ActionRequest, list[dict]]:
        if isinstance(policy, L1RulePolicy):
            choice = policy.choose_choice(state, actor, view)
            target_id = policy.choose_target(
                state,
                actor,
                view,
                choice=choice,
            )
            content, tool_calls = self._speech_content_with_tools(
                state,
                actor,
                view,
                policy,
            )
            return (
                ActionRequest(
                    action=view.action,
                    target_id=target_id,
                    content=content,
                    choice=choice,
                ),
                tool_calls,
            )

        rng = Random(
            f"{state.seed}:{policy.strategy_id}:"
            f"{len(state.events)}:{actor.player_id}:{view.action}"
        )
        choice = rng.choice(view.choices) if view.choices else None
        target_id: str | None = None
        if view.action == "witch_action":
            target_id = (
                None
                if choice == "none"
                else rng.choice(view.target_ids)
            )
        elif view.target_ids and (view.requires_target or view.allow_no_target):
            candidates: list[str | None] = list(view.target_ids)
            if view.allow_no_target:
                candidates.append(None)
            target_id = rng.choice(candidates)
        content, tool_calls = self._speech_content_with_tools(
            state,
            actor,
            view,
            policy,
        )
        return (
            ActionRequest(
                action=view.action,
                target_id=target_id,
                content=content,
                choice=choice,
            ),
            tool_calls,
        )

    @staticmethod
    def _speech_content(state, actor, view, policy) -> str | None:
        return AIController._speech_content_with_tools(
            state,
            actor,
            view,
            policy,
        )[0]

    @staticmethod
    def _speech_content_with_tools(
        state,
        actor,
        view,
        policy,
    ) -> tuple[str | None, list[dict]]:
        persona = getattr(policy, "archetype", None)
        if llm_speech_enabled():
            text, tool_calls = compose_speech_with_tools(
                state=state,
                actor=actor,
                view=view,
                persona=persona,
            )
            if text:
                return (
                    AIController._ensure_logic_catch(state, actor, view, text),
                    tool_calls,
                )
            return None, tool_calls
        if isinstance(policy, L1RulePolicy):
            return policy.choose_content(state, actor, view), []
        return speech_content(state, actor, view), []

    @staticmethod
    def _ensure_logic_catch(state, actor, view, text: str) -> str:
        """Prepend a hard contradiction the model should not have missed."""

        if view.action != "speech" or actor.role is Role.WEREWOLF:
            return text
        finding = strongest_finding(state, actor, exclude_speaker=actor.seat)
        if finding is None or finding.weight < 4:
            return text
        if str(finding.speaker_seat) in text:
            return text
        prefix = f"先抓{finding.speaker_seat}号一个漏洞：{finding.detail}。"
        return (prefix + text)[:140]

    @staticmethod
    def _host_id(state: GameState) -> str:
        # Seat 1 is the room creator in all current room creation paths.
        return state.players[0].player_id

    def _record_failure(
        self,
        room,
        *,
        actor_id: str | None,
        action: str,
        reason: str,
    ) -> None:
        append_event(
            room.state,
            EventType.AI_ACTION_FAILED,
            actor_id=actor_id,
            visibility=Visibility.PLAYER,
            visible_to=(room.host_player_id,),
            data={
                "action": action[:64],
                "reason": reason[:200],
            },
        )

    @staticmethod
    def _context_key(state: GameState) -> tuple[object, ...]:
        day_result = state.day_result
        night_result = state.night_result
        return (
            state.day,
            state.phase,
            len(state.events),
            state.wolf_captain_id,
            tuple(
                (player.player_id, player.is_alive)
                for player in sorted(state.players, key=lambda item: item.seat)
            ),
            None
            if day_result is None
            else (
                day_result.next_speaker_index,
                tuple(day_result.last_words_queue),
                tuple(sorted(day_result.votes.items())),
                day_result.votes_closed,
                day_result.vote_resolved,
                day_result.banishment_pending,
            ),
            None
            if night_result is None
            else (
                night_result.wolf_kill_submitted,
                night_result.seer_target_id,
                night_result.witch_action_submitted,
                night_result.resolved,
            ),
        )

    @staticmethod
    def _failure_reason(error: Exception) -> str:
        message = str(error).strip()
        return message or error.__class__.__name__


def _next_wolf_speaker(state: GameState, round_number: int) -> Player | None:
    spoken_ids = {
        event.actor_id
        for event in state.events
        if event.event_type is EventType.WOLF_SPEECH
        and event.day == state.day
        and event.data.get("round") == round_number
    }
    return next(
        (
            player
            for player in sorted(state.players, key=lambda item: item.seat)
            if player.is_alive
            and player.role is Role.WEREWOLF
            and player.player_id not in spoken_ids
        ),
        None,
    )
