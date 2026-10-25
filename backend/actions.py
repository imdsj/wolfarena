"""Server-authoritative action catalog and engine dispatch."""

from __future__ import annotations

import time

from .game_engine import (
    EventType,
    GameState,
    Phase,
    Player,
    Role,
    SPECTATOR_VIEW,
    begin_banishment_last_words,
    begin_day,
    close_self_destruct_window,
    close_vote,
    get_player,
    record_public_speech,
    record_wolf_speech,
    resolve_night,
    resolve_vote,
    select_wolf_kill,
    self_destruct,
    start_night,
    submit_day_hunter_shot,
    submit_last_words,
    submit_night_hunter_shot,
    submit_seer_check,
    submit_vote,
    submit_witch_action,
)
from .schemas import ActionRequest, ActionView


class ActionUnavailableError(ValueError):
    """The requested action is not legal for this viewer and phase."""


class ActionValidationError(ValueError):
    """The action exists, but its target, content, or choice is invalid."""


def available_actions_for_state(
    state: GameState,
    viewer: Player | str,
    *,
    host_player_id: str,
) -> tuple[ActionView, ...]:
    """Return only actions the authenticated viewer may perform now."""

    if viewer == SPECTATOR_VIEW or not isinstance(viewer, Player):
        return ()

    actions: list[ActionView] = []
    is_host = viewer.player_id == host_player_id
    living = _living_players(state)
    living_ids = [player.player_id for player in living]
    phase = state.phase

    def add(
        action: str,
        label: str,
        *,
        targets: list[str] | None = None,
        choices: list[str] | None = None,
        requires_content: bool = False,
        requires_target: bool = False,
        allow_no_target: bool = False,
    ) -> None:
        actions.append(
            ActionView(
                action=action,
                label=label,
                target_ids=targets or [],
                choices=choices or [],
                requires_content=requires_content,
                requires_target=requires_target,
                allow_no_target=allow_no_target,
            )
        )

    if phase is Phase.INIT:
        if is_host:
            add("start_night", "开始首夜")
        return tuple(actions)

    if phase in {
        Phase.NIGHT_WOLF_DISCUSSION_R1,
        Phase.NIGHT_WOLF_DISCUSSION_R2,
    }:
        round_number = (
            1 if phase is Phase.NIGHT_WOLF_DISCUSSION_R1 else 2
        )
        expected = _next_wolf_speaker(state, round_number)
        if (
            viewer.is_alive
            and viewer.role is Role.WEREWOLF
            and expected is not None
            and expected.player_id == viewer.player_id
        ):
            add(
                "wolf_speech",
                f"第 {round_number} 轮狼人发言",
                requires_content=True,
            )
        return tuple(actions)

    if phase is Phase.NIGHT_WOLF_KILL:
        if (
            viewer.is_alive
            and viewer.role is Role.WEREWOLF
            and state.wolf_captain_id == viewer.player_id
        ):
            add(
                "wolf_kill",
                "选择狼人击杀目标",
                targets=living_ids,
                allow_no_target=True,
            )
        return tuple(actions)

    if phase is Phase.NIGHT_SEER_CHECK:
        if viewer.is_alive and viewer.role is Role.SEER:
            add(
                "seer_check",
                "选择查验目标",
                targets=[
                    player_id
                    for player_id in living_ids
                    if player_id != viewer.player_id
                ],
                requires_target=True,
            )
        return tuple(actions)

    if phase is Phase.NIGHT_WITCH_ACTION:
        if viewer.is_alive and viewer.role is Role.WITCH:
            choices = ["none"]
            if state.antidote_available:
                choices.append("antidote")
            if state.poison_available:
                choices.append("poison")
            add(
                "witch_action",
                "女巫行动",
                targets=living_ids,
                choices=choices,
                allow_no_target=True,
            )
        return tuple(actions)

    if phase is Phase.NIGHT_RESOLUTION:
        if is_host:
            add("resolve_night", "结算夜晚")
        return tuple(actions)

    if phase is Phase.NIGHT_HUNTER_SHOT:
        night_result = state.night_result
        if (
            viewer.role is Role.HUNTER
            and night_result is not None
            and night_result.hunter_can_shoot
        ):
            add(
                "night_hunter_shot",
                "选择夜间开枪目标",
                targets=[
                    player_id
                    for player_id in living_ids
                    if player_id != viewer.player_id
                ],
                allow_no_target=True,
            )
        return tuple(actions)

    if phase is Phase.DAY_ANNOUNCEMENT:
        if is_host:
            add("begin_day", "开始白天")
        return tuple(actions)

    if phase is Phase.DAY_LAST_WORDS:
        day_result = state.day_result
        if (
            day_result is not None
            and day_result.last_words_queue
            and day_result.last_words_queue[0] == viewer.player_id
        ):
            add("last_words", "遗言", requires_content=True)
        return tuple(actions)

    if phase is Phase.DAY_DISCUSSION:
        day_result = state.day_result
        if day_result is not None:
            current_index = day_result.next_speaker_index
            while (
                current_index < len(day_result.speech_order)
                and not get_player(
                    state,
                    day_result.speech_order[current_index],
                ).is_alive
            ):
                current_index += 1
            if (
                current_index < len(day_result.speech_order)
                and day_result.speech_order[current_index] == viewer.player_id
            ):
                add("speech", "公开发言", requires_content=True)
        if viewer.is_alive and viewer.role is Role.WEREWOLF:
            add("self_destruct", "自爆")
        return tuple(actions)

    if phase is Phase.SELF_DESTRUCT:
        if viewer.is_alive and viewer.role is Role.WEREWOLF:
            add("self_destruct", "继续自爆")
        if is_host:
            add("close_self_destruct_window", "关闭自爆窗口")
        return tuple(actions)

    if phase is Phase.VOTE:
        day_result = state.day_result
        if day_result is not None and not day_result.votes_closed:
            if viewer.is_alive:
                add(
                    "vote",
                    "投票或弃权",
                    targets=living_ids,
                    allow_no_target=True,
                )
            if is_host:
                add("close_vote", "截止投票")
        elif (
            day_result is not None
            and day_result.votes_closed
            and not day_result.vote_resolved
        ):
            if is_host:
                add("resolve_vote", "结算投票")
        elif (
            day_result is not None
            and day_result.vote_resolved
            and day_result.banishment_pending
        ):
            if is_host:
                add(
                    "begin_banishment_last_words",
                    "开始放逐遗言",
                )
        return tuple(actions)

    if phase is Phase.DAY_HUNTER_SHOT:
        day_result = state.day_result
        if (
            viewer.role is Role.HUNTER
            and day_result is not None
            and day_result.day_hunter_can_shoot
        ):
            add(
                "day_hunter_shot",
                "选择白天开枪目标",
                targets=[
                    player_id
                    for player_id in living_ids
                    if player_id != viewer.player_id
                ],
                allow_no_target=True,
            )
        return tuple(actions)

    return tuple(actions)


def execute_engine_action(
    state: GameState,
    viewer: Player,
    request: ActionRequest,
    *,
    host_player_id: str,
    now: float | None = None,
) -> None:
    """Validate one action and dispatch it through the existing rules engine."""

    actions = {
        action.action: action
        for action in available_actions_for_state(
            state,
            viewer,
            host_player_id=host_player_id,
        )
    }
    view = actions.get(request.action)
    if view is None:
        raise ActionUnavailableError(
            f"当前玩家不能执行动作：{request.action}"
        )

    _validate_request(request, view)
    action = request.action
    actor_id = viewer.player_id
    action_now = time.time() if now is None else now

    if action == "start_night":
        start_night(state)
    elif action == "wolf_speech":
        round_number = (
            1 if state.phase is Phase.NIGHT_WOLF_DISCUSSION_R1 else 2
        )
        record_wolf_speech(
            state,
            actor_id,
            round_number,
            _required_content(request),
        )
    elif action == "wolf_kill":
        select_wolf_kill(state, actor_id, request.target_id)
    elif action == "seer_check":
        submit_seer_check(state, actor_id, request.target_id or "")
    elif action == "witch_action":
        submit_witch_action(
            state,
            actor_id,
            request.choice or "",
            request.target_id,
        )
    elif action == "resolve_night":
        resolve_night(state)
    elif action == "night_hunter_shot":
        submit_night_hunter_shot(state, actor_id, request.target_id)
    elif action == "begin_day":
        begin_day(state, now=action_now)
    elif action == "last_words":
        submit_last_words(
            state,
            actor_id,
            _required_content(request),
            now=action_now,
        )
    elif action == "speech":
        record_public_speech(
            state,
            actor_id,
            _required_content(request),
            now=action_now,
        )
    elif action == "self_destruct":
        self_destruct(state, actor_id, action_now)
    elif action == "close_self_destruct_window":
        close_self_destruct_window(state, now=action_now)
    elif action == "vote":
        submit_vote(state, actor_id, request.target_id)
    elif action == "close_vote":
        close_vote(state)
    elif action == "resolve_vote":
        resolve_vote(state)
    elif action == "begin_banishment_last_words":
        begin_banishment_last_words(state)
    elif action == "day_hunter_shot":
        submit_day_hunter_shot(state, actor_id, request.target_id)
    else:
        raise ActionUnavailableError(f"未接入动作：{action}")


def _validate_request(request: ActionRequest, view: ActionView) -> None:
    if view.requires_content and (
        request.content is None or not request.content.strip()
    ):
        raise ActionValidationError("该动作必须提供非空 content")
    if not view.requires_content and request.content not in {None, ""}:
        raise ActionValidationError("该动作不接受 content")

    if view.choices and request.choice not in view.choices:
        raise ActionValidationError(
            f"choice 必须是：{', '.join(view.choices)}"
        )
    if not view.choices and request.choice not in {None, ""}:
        raise ActionValidationError("该动作不接受 choice")

    if view.requires_target and request.target_id is None:
        raise ActionValidationError("该动作必须提供 target_id")
    if request.target_id is not None and request.target_id not in view.target_ids:
        raise ActionValidationError("target_id 不在当前合法目标中")
    if (
        request.target_id is None
        and not view.allow_no_target
        and view.target_ids
    ):
        raise ActionValidationError("该动作必须从合法目标中选择")
    if (
        request.action == "witch_action"
        and request.choice in {"antidote", "poison"}
        and request.target_id is None
    ):
        raise ActionValidationError("使用药物时必须指定目标")
    if (
        request.action == "witch_action"
        and request.choice == "none"
        and request.target_id is not None
    ):
        raise ActionValidationError("不使用药物时不能指定目标")


def _required_content(request: ActionRequest) -> str:
    if request.content is None:
        raise ActionValidationError("缺少 content")
    return request.content


def _living_players(state: GameState) -> list[Player]:
    return [
        player
        for player in sorted(state.players, key=lambda item: item.seat)
        if player.is_alive
    ]


def _next_wolf_speaker(
    state: GameState,
    round_number: int,
) -> Player | None:
    spoken_ids = {
        event.actor_id
        for event in state.events
        if event.event_type is EventType.WOLF_SPEECH
        and event.day == state.day
        and event.data.get("round") == round_number
    }
    for player in _living_players(state):
        if (
            player.role is Role.WEREWOLF
            and player.player_id not in spoken_ids
        ):
            return player
    return None
