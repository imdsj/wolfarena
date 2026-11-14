"""Whitelisted, read-only tools an agent may call while deciding.

Every tool is bound to the caller's own ``state`` and ``actor``. It never opens
arbitrary paths, never runs code and never reads another player's hidden role.
The three tools accept no parameters; any supplied argument is rejected.
"""

from __future__ import annotations

from pathlib import Path

from .game_engine import GameState
from .logic_audit import audit
from .tactic_retrieval import rank_tactics
from .vote_analysis import format_vote_analysis


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGY_ROOT = PROJECT_ROOT / "strategy_library"

TOOL_NAMES: tuple[str, ...] = ("audit_logic", "analyze_votes", "search_tactics")


TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "audit_logic",
            "description": (
                "审计当前可见发言中的硬规则与逻辑矛盾，例如一晚两验、"
                "票死人、身份前后矛盾。返回结构化发现，供发言引用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_votes",
            "description": (
                "汇总公开票型，找出连续同票、绑票与未跟最高票的玩家。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_tactics",
            "description": (
                "按当前公开局面检索本地策略库中的种子与已验证战术，"
                "返回触发条件、建议、风险与来源。"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


def audit_logic(state: GameState, actor) -> dict:
    findings = [
        {
            "kind": finding.kind,
            "speaker_seat": finding.speaker_seat,
            "subject_seat": finding.subject_seat,
            "weight": finding.weight,
            "detail": finding.detail,
        }
        for finding in audit(state, actor)
    ]
    return {
        "findings": findings,
        "strongest": findings[0]["detail"] if findings else None,
    }


def analyze_votes(state: GameState, actor) -> dict:
    summary = format_vote_analysis(state, actor)
    return {"summary": summary or "当前还没有公开票型。"}


def search_tactics(state: GameState, actor) -> dict:
    matches = rank_tactics(state, actor, root=STRATEGY_ROOT, limit=3)
    return {
        "tactics": [
            {
                "strategy_id": match.card.strategy_id,
                "title": match.card.title,
                "trigger": match.card.trigger,
                "recommendation": match.card.recommendation,
                "risk": match.card.risk,
                "source": match.card.source,
                "evidence_level": match.card.evidence_level,
            }
            for match in matches
        ]
    }


def execute_tool(
    name: str,
    arguments: dict | None,
    state: GameState,
    actor,
) -> dict:
    """Run one whitelisted tool, rejecting unknown names and parameters."""

    if name not in TOOL_NAMES:
        raise ValueError(f"未知工具：{name}")
    if arguments:
        raise ValueError(f"工具 {name} 不接受参数")
    if name == "audit_logic":
        return audit_logic(state, actor)
    if name == "analyze_votes":
        return analyze_votes(state, actor)
    return search_tactics(state, actor)


__all__ = [
    "STRATEGY_ROOT",
    "TOOL_DEFINITIONS",
    "TOOL_NAMES",
    "analyze_votes",
    "audit_logic",
    "execute_tool",
    "search_tactics",
]
