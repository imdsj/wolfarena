"""Optional LLM-driven in-game speech, with a template fallback.

This is deliberately behind an environment flag (WOLFARENA_LLM_SPEECH=1) so
the deterministic rule/template path remains the default and the training
pipeline is unaffected. The prompt only uses public information plus the
speaker's own role; it never reads another player's hidden identity.
"""

from __future__ import annotations

import os

import httpx

from .ai_provider import DeepSeekSettings
from .game_engine import EventType, GameState, get_visible_events

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
    system = (
        f"你在 WolfArena 九人狼人杀中扮演 {actor.seat} 号，真实身份是{role_label}。"
        "你的目标是用自然的中文发言帮助你的阵营获胜。规则：只使用公开信息；"
        "狼人必须伪装成好人，不得暴露身份；可以引用其他玩家的座位号和发言；"
        "不要承认自己是 AI。输出一句到两句，80 字以内。"
    )
    user = (
        f"第 {state.day} 天，当前阶段 {state.phase.value}。"
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
