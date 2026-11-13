"""Optional LLM-driven in-game speech, with a template fallback.

This is deliberately behind an environment flag (WOLFARENA_LLM_SPEECH=1) so
the deterministic rule/template path remains the default and the training
pipeline is unaffected. The prompt only uses public information plus the
speaker's own role; it never reads another player's hidden identity.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from .agent_tools import TOOL_DEFINITIONS, execute_tool
from .ai_provider import DeepSeekSettings
from .game_engine import EventType, GameState, Role, get_visible_events
from .llm_budget import LEDGER
from .logic_audit import (
    asserts_unspoken_identity,
    audit,
    contradicts_own_report,
    dead_vote_targets,
    impossible_seer_claim_in_text,
    mentions_two_nights_on_day_one,
    speech_claims_living_dead,
    wolf_speech_targets_dead,
)
from .rulebook import rules_brief
from .speech_quality import is_repetitive
from .strategy_library import StrategyLibrary
from .personas import persona_guidance
from .vote_analysis import format_vote_analysis

STRATEGY_ROOT = Path(__file__).resolve().parent.parent / "strategy_library"

ROLE_LABELS = {
    "werewolf": "狼人",
    "villager": "村民",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
}

SPEECH_STYLES = (
    "沉稳型：先给结论，再用一两条证据支撑",
    "直球型：直接点矛盾，敢归票",
    "谨慎型：先听两边，说清自己还缺什么信息",
    "强势型：敢定票，但必须给出理由",
    "简练型：少说废话，只讲本轮关键变化",
)

ROLE_PERSONA = {
    "werewolf": (
        "你是狼人。白天必须伪装成好人，可以撒谎、误导他人、把嫌疑转移给别的玩家；"
        "要和狼队友保持一致，绝不要攻击队友；如果有队友被怀疑，可以帮他辩护，"
        "也可以在必要时放弃他保全自己。残局只剩3人且你们2狼在场时，白天合力投走最后一个好人就能直接获胜。"
        "有真预言家跳出来时，你们必须有一个狼人悍跳预言家去对跳，编造查验把水搅浑，不要胆怯。"
        "夜晚可以自刀（刀自己人）来骗女巫解药或伪装身份，不要害怕自刀。"
    ),
    "seer": (
        "你是预言家。第一天就要跳出来报查验结果（金水或查杀），带领好人归票，不要等死后才在遗言里说。"
        "报完查验后要给出明确的归票方向，并说明你下一个要验谁。"
        "如果有人也声称是预言家，那个人一定是狼人在悍跳，要立刻指认对方、报清你的查验历史，号召好人票他。"
    ),
    "witch": (
        "你是女巫。白天要隐藏身份，可以暗示你昨晚救过人，但不要轻易暴露自己是女巫，"
        "否则会成为狼人的目标。谨慎使用解药和毒药，确认对方是狼再下毒。"
    ),
    "hunter": (
        "你是猎人。发言要符合逻辑，观察别人前后矛盾的地方；可以用猎人身份威慑狼人，但注意时机。"
        "投票坚定站在好人一边，投最可疑的玩家。"
    ),
    "villager": (
        "你是村民，没有任何技能，只能靠白天的发言和投票。要仔细分析每句话里的漏洞，"
        "清晰说出你怀疑谁、为什么，不要情绪化，不要轻信任何人。"
        "如果场上出现两个预言家，必然一真一假，要对比两人的查验和状态，不要盲目跟风。"
        "预言家每晚查验一个不同的人是正常规则，不要因此说他逻辑混乱或前后矛盾。"
        "如果你被别人发了金水，不要立刻站边；狼人也可能给你金水来拉票，要对比两个预言家的查验时间和发言再决定。"
    ),
}

DEATH_CAUSE_LABELS = {
    "wolf_kill": "被狼人刀",
    "poisoned": "被女巫毒",
    "vote": "被投票放逐",
    "hunter_shot": "被猎人开枪带走",
    "self_destruct": "自爆",
}


def llm_speech_enabled() -> bool:
    return os.getenv("WOLFARENA_LLM_SPEECH", "0") == "1"


def public_history(state: GameState, actor) -> list[str]:
    lines: list[str] = []
    for event in get_visible_events(state, actor):
        if event.event_type not in {
            EventType.PUBLIC_SPEECH,
            EventType.LAST_WORDS,
        }:
            continue
        content = event.data.get("content")
        if event.actor_id and isinstance(content, str):
            speaker = next(
                (p for p in state.players if p.player_id == event.actor_id),
                None,
            )
            seat = speaker.seat if speaker else "?"
            lines.append(f"{seat} 号：{content}")
    return lines


def wolf_history(state: GameState, actor) -> list[str]:
    """The wolf-team private channel, only readable by wolves."""

    lines: list[str] = []
    for event in get_visible_events(state, actor):
        if event.event_type is not EventType.WOLF_SPEECH:
            continue
        content = event.data.get("content")
        if event.actor_id and isinstance(content, str):
            seat = _seat_of(state, event.actor_id)
            lines.append(f"{seat} 号：{content}")
    return lines


def _own_last_speech(state: GameState, actor) -> str:
    """The speaker's own most recent public sentence, for anti-repetition."""

    for event in reversed(get_visible_events(state, actor)):
        if event.event_type not in {
            EventType.PUBLIC_SPEECH,
            EventType.LAST_WORDS,
        }:
            continue
        if event.actor_id != actor.player_id:
            continue
        content = event.data.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def _style_for(state: GameState, actor) -> str:
    return SPEECH_STYLES[(state.seed + actor.seat) % len(SPEECH_STYLES)]


def private_context(state: GameState, actor) -> str:
    """The speaker's own knowledge, mirroring the reference GameMaster prompt."""

    role = actor.role
    if role is Role.SEER:
        checks: list[str] = []
        for event in get_visible_events(state, actor):
            if event.event_type is not EventType.SEER_CHECKED or not event.target_id:
                continue
            target = next(
                (
                    player
                    for player in state.players
                    if player.player_id == event.target_id
                ),
                None,
            )
            seat = target.seat if target else "?"
            result = event.data.get("result")
            checks.append(
                f"{seat} 号是{'狼人' if result == 'wolf' else '好人'}"
            )
        if checks:
            return (
                "你的查验历史：" + "；".join(checks) + "。"
                "只能陈述这些真实查验结果，不得编造。"
            )
        return "你还没有查验过任何人，不要声称查验结果。"

    if role is Role.WITCH:
        antidote = "可用" if state.antidote_available else "已用"
        poison = "可用" if state.poison_available else "已用"
        return f"你的药剂：解药[{antidote}]，毒药[{poison}]。"

    if role is Role.WEREWOLF:
        teammates = [
            player.seat
            for player in state.players
            if player.role is Role.WEREWOLF
            and player.player_id != actor.player_id
        ]
        names = "、".join(f"{seat} 号" for seat in teammates) or "已无"
        lines = [f"你的狼人队友是：{names}。白天必须伪装，不能承认狼人身份。"]
        alive = [
            player.seat for player in state.players if player.is_alive
        ]
        dead = [
            player.seat for player in state.players if not player.is_alive
        ]
        lines.append(
            f"场上存活：{'、'.join(str(seat) for seat in alive)}；"
            f"已出局：{'、'.join(str(seat) for seat in dead) or '无'}。"
            "刀口只能从存活玩家里选，绝不能刀已经出局的玩家。"
        )
        night_result = state.night_result
        if night_result is not None and night_result.wolf_target_id:
            target = next(
                (
                    player
                    for player in state.players
                    if player.player_id == night_result.wolf_target_id
                ),
                None,
            )
            if target is not None:
                lines.append(f"你方昨晚的刀口是：{target.seat} 号。")
        return "\n".join(lines)

    if role is Role.HUNTER:
        return "你是猎人，出局时可以开枪带走一人。"

    return "你是普通村民，没有额外信息。"


def night_summary(state: GameState) -> str:
    if state.day == 0:
        return "首夜，尚无公开结果。"
    day_result = state.day_result
    if day_result is not None and day_result.announced_death_ids:
        seats = [
            player.seat
            for player in state.players
            if player.player_id in day_result.announced_death_ids
        ]
        return "昨晚 " + "、".join(f"{seat} 号" for seat in seats) + " 死亡。"
    return "昨晚是平安夜。"


def dead_notice(state: GameState, actor) -> str:
    """Tell a last-words speaker that they are out of the game for good."""

    causes: list[str] = []
    day_result = state.day_result
    if day_result is not None:
        raw = day_result.death_causes.get(actor.player_id) or []
        causes = [DEATH_CAUSE_LABELS.get(cause, cause) for cause in raw]
    reason = f"（{'、'.join(causes)}）" if causes else ""
    if actor.role is Role.WEREWOLF:
        return (
            f"你已经出局{reason}，现在只能发表遗言。"
            "你是狼人，绝对不能承认自己是狼，也不要认输、不要夸好人站对边。"
            "要反咬预言家是假预言家、质疑他的查杀是编的，尽量把水搅浑，"
            "保护还活着的狼队友。不要说“我后面听你说”“下一轮再说”这类话。"
        )
    return (
        f"你已经出局{reason}，现在只能发表遗言。"
        "你不能再参与后续的发言、投票、开枪或任何行动，也不会再回到游戏里。"
        "绝对不要说“我后面听你说”“下一轮我再解释”“等我再观察”这类话。"
        "请交代你掌握的信息，并给还活着的队友留下明确建议。"
    )


def tactic_query(state: GameState, actor) -> str:
    """Build a retrieval query exclusively from information visible to actor."""

    lines = public_history(state, actor)[-6:]
    lines.extend(finding.detail for finding in audit(state, actor)[-3:])
    votes = format_vote_analysis(state, actor)
    if votes:
        lines.append(votes)
    return "\n".join(lines)


def tactics_context(state: GameState, actor) -> str:
    """Retrieve sourced tactics relevant to the actor's current public board."""

    matches = StrategyLibrary(STRATEGY_ROOT).search(
        tactic_query(state, actor),
        role=actor.role.value,
        phase=state.phase.value,
        limit=3,
    )
    if not matches:
        return ""
    lines = [
        f"- [{match.card.strategy_id}] {match.card.title}\n"
        f"  触发：{match.card.trigger}\n"
        f"  建议：{match.card.recommendation}\n"
        f"  风险：{match.card.risk}\n"
        f"  来源：{match.card.source}（{match.card.evidence_level}）"
        for match in matches
    ]
    return (
        "战术库参考（按当前局面检索，供你借鉴，不是强制指令；"
        "不要在发言中念出策略编号）：\n" + "\n".join(lines)
    )


def _seat_of(state: GameState, player_id: str | None) -> str:
    if not player_id:
        return "?"
    for player in state.players:
        if player.player_id == player_id:
            return str(player.seat)
    return "?"


def game_timeline(state: GameState, actor, *, limit: int = 18) -> str:
    """A compact seat-numbered trail of deaths, shots and votes."""

    lines: list[str] = []
    for event in reversed(get_visible_events(state, actor)):
        if event.event_type is EventType.PLAYER_DIED:
            causes = event.data.get("causes")
            cause_text = (
                "、".join(
                    DEATH_CAUSE_LABELS.get(cause, cause)
                    for cause in causes
                    if isinstance(cause, str)
                )
                if isinstance(causes, list)
                else ""
            )
            suffix = f"（{cause_text}）" if cause_text else ""
            lines.append(f"{_seat_of(state, event.target_id)} 号出局{suffix}")
        elif event.event_type is EventType.HUNTER_SHOT:
            lines.append(
                f"{_seat_of(state, event.actor_id)} 号开枪带走 "
                f"{_seat_of(state, event.target_id)} 号"
            )
        elif event.event_type is EventType.SELF_DESTRUCTED:
            lines.append(f"{_seat_of(state, event.actor_id)} 号自爆")
        elif event.event_type is EventType.VOTE_RESULT and event.target_id:
            lines.append(f"投票放逐 {_seat_of(state, event.target_id)} 号")
        if len(lines) >= limit:
            break
    lines.reverse()
    return "\n".join(lines)


def speaking_order(state: GameState, actor) -> str:
    """Current speaker position and the full seat order for today."""

    day_result = state.day_result
    if day_result is None or not day_result.speech_order:
        return ""
    seats = [_seat_of(state, player_id) for player_id in day_result.speech_order]
    actor_seat = _seat_of(state, actor.player_id)
    if actor_seat not in seats:
        # A night-death speaker giving last words is not part of today's
        # living speaking order, so there is no position to report.
        return ""
    position = seats.index(actor_seat) + 1
    return f"发言顺序：{' → '.join(seats)}（你是第 {position} 个）"


def _tool_call_summary(name: str, result: dict) -> dict:
    """A compact, serializable record of one tool call for the decision trace."""

    if name == "audit_logic":
        return {
            "name": name,
            "findings": len(result.get("findings", [])),
            "strongest": result.get("strongest"),
        }
    if name == "analyze_votes":
        return {
            "name": name,
            "summary": (result.get("summary") or "")[:160],
        }
    if name == "search_tactics":
        return {
            "name": name,
            "tactic_ids": [
                tactic.get("strategy_id")
                for tactic in result.get("tactics", [])
            ],
        }
    return {"name": name}


def compose_speech(
    *,
    state: GameState,
    actor,
    view,
    settings: DeepSeekSettings | None = None,
    persona=None,
) -> str | None:
    """Return an LLM speech, or None so the caller falls back to templates."""

    text, _ = compose_speech_with_tools(
        state=state,
        actor=actor,
        view=view,
        settings=settings,
        persona=persona,
    )
    return text


def compose_speech_with_tools(
    *,
    state: GameState,
    actor,
    view,
    settings: DeepSeekSettings | None = None,
    persona=None,
) -> tuple[str | None, list[dict]]:
    """LLM speech with an optional whitelisted tool-calling loop.

    The model may call ``audit_logic``, ``analyze_votes`` or ``search_tactics``
    before writing its sentence. Tool results stay inside the prompt and are
    returned as a compact trace so the caller can record them.
    """

    if not view.requires_content or view.action not in {
        "speech",
        "last_words",
        "wolf_speech",
    }:
        return None, []
    config = settings or DeepSeekSettings.from_environment()
    if not config.api_key:
        return None, []

    role = actor.role.value
    role_label = ROLE_LABELS.get(role, role)
    roster = [
        f"{player.seat} 号"
        for player in state.players
        if player.is_alive
    ]
    history = public_history(state, actor)[-12:]
    private_info = private_context(state, actor)
    public_result = night_summary(state)
    tactics = tactics_context(state, actor)
    timeline = game_timeline(state, actor)
    audit_lines = [finding.detail for finding in audit(state, actor)[-3:]]
    audit_block = (
        "=== 逻辑审计（只基于公开信息，可直接作为质疑点）===\n"
        + "\n".join(f"- {line}" for line in audit_lines)
        + "\n"
        if audit_lines
        else ""
    )
    vote_lines = format_vote_analysis(state, actor)
    vote_block = (
        "=== 历史票型（谁投给了谁，可用来抓同票/绑票）===\n"
        + vote_lines
        + "\n"
        if vote_lines
        else ""
    )
    order_info = speaking_order(state, actor)
    is_last_words = view.action == "last_words"
    is_wolf_speech = view.action == "wolf_speech"
    death_line = dead_notice(state, actor) if is_last_words else ""
    tactics_block = ("=== RAG 检索结果 ===\n" + tactics + "\n") if tactics else ""
    history_block = "\n".join(history) if history else "你是第一个发言。"
    own_last = _own_last_speech(state, actor)
    style = _style_for(state, actor)
    guidance = persona_guidance(persona)
    wolf_plan_block = ""
    if role == "werewolf" and not is_last_words:
        wolf_lines = wolf_history(state, actor)[-8:]
        if wolf_lines:
            wolf_plan_block = (
                "=== 你们狼队的夜间战术（白天必须照着执行）===\n"
                + "\n".join(wolf_lines)
                + "\n白天按计划走：该悍跳的悍跳、该跟票的跟票、该低调的低调，不要临场改口。\n"
            )
    spoken_seats: set[str] = set()
    if state.day_result is not None and state.day_result.speech_order:
        for player_id in state.day_result.speech_order[
            : state.day_result.next_speaker_index
        ]:
            spoken_seats.add(_seat_of(state, player_id))
    unspoken = [
        str(player.seat)
        for player in state.players
        if player.is_alive and str(player.seat) not in spoken_seats
    ]
    unspoken_block = (
        "还没发言，禁止评价他们的发言内容：" + "、".join(unspoken)
        if unspoken
        else ""
    )
    dead_seats = [
        str(player.seat) for player in state.players if not player.is_alive
    ]
    dead_seat_set = {player.seat for player in state.players if not player.is_alive}
    dead_block = f"- 已出局（死人，不在场）：{'、'.join(dead_seats) or '无'}\n"
    if is_wolf_speech:
        wolf_lines = wolf_history(state, actor)[-10:]
        wolf_history_block = (
            "\n".join(wolf_lines) if wolf_lines else "还没有狼队讨论。"
        )
        system = (
            f"你在 WolfArena 九人狼人杀中扮演 {actor.seat} 号，身份是狼人。"
            "现在是狼人私密频道，只有狼人能看到，好人和预言家都看不到这里。"
            "要听懂队友（尤其是真人玩家）的战术安排，并给出可执行的回应："
            "今晚刀谁、白天谁去悍跳预言家、谁去跟票、谁去踩人。"
            "可以讨论自刀骗药、对跳预言家，不要胆怯，定下来白天就照做。"
            "不能暴露狼人身份。绝不能点名还没发言的玩家是预言家/女巫/猎人，"
            "那等于承认你掌握了不该知道的信息。"
            "只能从存活玩家里选择刀口，绝不能刀已经出局的玩家。"
            f"你的说话风格：{style}。保持风格，但不要复述队友已经说过的话。"
            + guidance
            + "只输出一句到两句中文，80 字以内。\n" + rules_brief()
        )
        user = (
            f"第 {state.day} 天夜晚，狼队讨论环节。\n"
            f"=== 你的私密信息 ===\n{private_info}\n\n"
            f"=== 场上状态 ===\n"
            f"- 存活玩家：{'、'.join(roster)}\n"
            f"- 已出局（不在场，不能刀）：{'、'.join(dead_seats) or '无'}\n\n"
            f"=== 最近的狼队频道发言 ===\n{wolf_history_block}\n"
            f"{audit_block}"
            f"{vote_block}"
            f"{tactics_block}"
            f"请以 {actor.seat} 号的身份回应队友，给出你的建议。"
        )
    else:
        system = (
            f"你在 WolfArena 九人狼人杀中扮演 {actor.seat} 号，真实身份是{role_label}。"
            f"{ROLE_PERSONA.get(role, '')}"
            "发言要求：必须回应或评价在场其他玩家的发言，不能自说自话；"
            "可以引用座位号和别人的原话；不要承认自己是 AI。"
            "死亡信息只以【本轮公开信息】里的昨晚结果为准，绝对不能编造谁死了、谁被票了。"
            "场上存活/出局名单也必须以【本轮公开信息】为准，绝不能把活人说成死人。"
            "已出局的人不能再被票、被刀、被验；不要号召票死人。"
            "不能刚说某人是金水/好人，又要票他。"
            "对还没发言的玩家，只能表示怀疑或等待，绝不能断言其神职身份；"
            "如果发现别人对未发言玩家下身份结论，要直接点破这个逻辑漏洞。"
            "只输出一句到两句中文发言，90 字以内。"
            + ("你现在已经出局，只能留遗言。" if is_last_words else "")
            + f"你的说话风格：{style}。保持风格，但逻辑优先。"
            + guidance
            + "\n" + rules_brief()
        )
        user = (
            f"现在是第 {state.day} 天的{'遗言' if is_last_words else '白天发言'}环节。"
            f"{order_info}\n"
            f"{death_line}"
            f"=== 你的私密信息 ===\n{private_info}\n\n"
            f"=== 本局事件 ===\n{timeline or '暂无'}\n\n"
            f"{audit_block}"
            f"{vote_block}"
            f"=== 本轮公开信息 ===\n"
            f"- 昨晚结果：{public_result}\n"
            f"- 存活玩家：{'、'.join(roster)}\n"
            f"{dead_block}"
            f"=== 你上一轮说过 ===\n{own_last or '无（这是你第一次发言）'}\n"
            "本轮必须给出新的判断、质疑或票型分析，禁止复述上一轮或别人说过的话。\n"
            f"- 已发言：{'、'.join(sorted(spoken_seats)) or '无'}\n"
            f"- {unspoken_block}\n"
            f"- 今日发言：\n"
            + history_block
            + "\n"
            + wolf_plan_block
            + tactics_block
            + f"请以 {actor.seat} 号的身份发表本轮发言。"
        )

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    tool_calls_summary: list[dict] = []
    content: str | None = None
    try:
        with httpx.Client(timeout=8.0) as client:
            request_body = {
                "model": config.model,
                "messages": messages,
                "temperature": 0.8,
                "presence_penalty": 0.6,
                "frequency_penalty": 0.4,
                "max_tokens": 180,
                "tools": TOOL_DEFINITIONS,
            }
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            response.raise_for_status()
            body = response.json()
            LEDGER.record(
                source="speech",
                usage=body.get("usage"),
                prompt_chars=len(system) + len(user),
                completion_chars=len(
                    str(body["choices"][0]["message"].get("content") or "")
                ),
            )
            message = body["choices"][0]["message"]
            content = message.get("content")
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                messages.append(message)
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = function.get("name", "")
                    arguments_text = function.get("arguments") or "{}"
                    try:
                        arguments = json.loads(arguments_text)
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}
                    try:
                        result = execute_tool(name, arguments, state, actor)
                        tool_calls_summary.append(
                            _tool_call_summary(name, result)
                        )
                    except Exception as error:
                        result = {"error": str(error)}
                        tool_calls_summary.append(
                            {"name": name, "error": str(error)}
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                second_response = client.post(
                    f"{config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": config.model,
                        "messages": messages,
                        "temperature": 0.8,
                        "max_tokens": 180,
                    },
                )
                second_response.raise_for_status()
                second_body = second_response.json()
                LEDGER.record(
                    source="speech",
                    usage=second_body.get("usage"),
                    prompt_chars=sum(
                        len(str(item.get("content") or ""))
                        for item in messages
                    ),
                    completion_chars=len(
                        str(
                            second_body["choices"][0]["message"].get(
                                "content"
                            )
                            or ""
                        )
                    ),
                )
                content = second_body["choices"][0]["message"].get("content")
    except Exception:
        LEDGER.record_failure()
        return None, tool_calls_summary

    cleaned = " ".join(str(content).split())[:140] if content else ""
    if not cleaned:
        return None, tool_calls_summary
    try:
        unspoken_seats = {int(seat) for seat in unspoken}
    except ValueError:
        unspoken_seats = set()
    alive_seats = {player.seat for player in state.players if player.is_alive}
    dead_seats = {
        player.seat for player in state.players if not player.is_alive
    }
    prior_texts = list(history[-12:])
    if own_last:
        prior_texts.append(own_last)
    if (
        asserts_unspoken_identity(cleaned, unspoken_seats, actor.seat)
        or speech_claims_living_dead(cleaned, alive_seats)
        or contradicts_own_report(cleaned)
        or dead_vote_targets(cleaned, dead_seat_set)
        or is_repetitive(cleaned, prior_texts)
        or impossible_seer_claim_in_text(cleaned, state.day)
        or mentions_two_nights_on_day_one(cleaned, state.day)
        or (
            actor.role is Role.WEREWOLF
            and wolf_speech_targets_dead(cleaned, dead_seats)
        )
    ):
        # The model leaked information a player could not have. Drop the
        # sentence and let the deterministic template speak instead.
        return None, tool_calls_summary
    return cleaned, tool_calls_summary
