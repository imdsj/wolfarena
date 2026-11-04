"""Optional LLM-driven in-game speech, with a template fallback.

This is deliberately behind an environment flag (WOLFARENA_LLM_SPEECH=1) so
the deterministic rule/template path remains the default and the training
pipeline is unaffected. The prompt only uses public information plus the
speaker's own role; it never reads another player's hidden identity.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx

from .ai_provider import DeepSeekSettings
from .game_engine import EventType, GameState, Role, get_visible_events
from .strategy_library import StrategyLibrary

STRATEGY_ROOT = Path(__file__).resolve().parent.parent / "strategy_library"

ROLE_LABELS = {
    "werewolf": "狼人",
    "villager": "村民",
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
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
        return f"你的狼人队友是：{names}。白天必须伪装，不能承认狼人身份。"

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


def tactics_context(state: GameState, actor) -> str:
    """Ground the speaker in the curated strategy library for its role/phase."""

    try:
        library = StrategyLibrary(STRATEGY_ROOT)
        matches = library.search(
            "",
            role=actor.role.value,
            phase=state.phase.value,
            limit=3,
        )
    except Exception:
        matches = []
    if not matches:
        return ""
    lines = [
        f"- {match.card.title}：{match.card.recommendation}"
        f"（风险：{match.card.risk}）"
        for match in matches
    ]
    return "战术库参考（沉淀自过往经验，供你借鉴，不是强制指令）：\n" + "\n".join(lines)


def compose_speech(
    *,
    state: GameState,
    actor,
    view,
    settings: DeepSeekSettings | None = None,
) -> str | None:
    """Return an LLM speech, or None so the caller falls back to templates."""

    if not view.requires_content or view.action not in {"speech", "last_words"}:
        return None
    config = settings or DeepSeekSettings.from_environment()
    if not config.api_key:
        return None

    role = actor.role.value
    role_label = ROLE_LABELS.get(role, role)
    roster = [
        f"{player.seat} 号"
        for player in state.players
        if player.is_alive
    ]
    history = public_history(state, actor)[-8:]
    private_info = private_context(state, actor)
    public_result = night_summary(state)
    tactics = tactics_context(state, actor)
    system = (
        f"你在 WolfArena 九人狼人杀中扮演 {actor.seat} 号，真实身份是{role_label}。"
        "你的目标是用自然的中文发言帮助你的阵营获胜。规则：只使用公开信息；"
        "狼人必须伪装成好人，不得暴露身份；可以引用其他玩家的座位号和发言；"
        "不要承认自己是 AI。输出一句到两句，80 字以内。"
    )
    user = (
        f"第 {state.day} 天，当前阶段 {state.phase.value}。"
        f"昨晚结果：{public_result}"
        f"你的私密信息：{private_info}"
        f"战术参考：{tactics or '无'}"
        f"在场玩家：{'、'.join(roster)}。"
        f"最近的公开发言：{' / '.join(history) if history else '暂无'}。"
        f"请以 {actor.seat} 号的身份发表本轮发言。"
    )
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 180,
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except Exception:
        return None
    cleaned = " ".join(str(content).split())[:140]
    return cleaned or None
