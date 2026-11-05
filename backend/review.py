"""Post-game review: turn finished games into candidate strategy cards.

This is the first link of the experience loop: finished games are summarized
into lessons that land in ``strategy_library/candidates``. Promotion to
``validated`` still requires the existing 200-game evidence plus a human
reviewer, so a lesson never reaches the retrieval set without proof.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import httpx

from .ai_provider import DeepSeekSettings
from .strategy_library import (
    STRATEGY_TOOL_PHASES,
    StrategyCard,
    StrategyLibrary,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_ROLES = {"werewolf", "villager", "seer", "witch", "hunter"}


def _clip(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _sanitize_lesson(lesson: dict[str, Any]) -> dict[str, Any]:
    role = lesson.get("role")
    if role not in ALLOWED_ROLES:
        role = "villager"
    phase = lesson.get("phase")
    if phase not in STRATEGY_TOOL_PHASES:
        phase = "ANY"
    return {
        "title": _clip(lesson.get("title"), 120) or "复盘教训",
        "role": role,
        "phase": phase,
        "action": _clip(lesson.get("action"), 64) or "vote",
        "trigger": _clip(lesson.get("trigger"), 600),
        "recommendation": _clip(lesson.get("recommendation"), 600),
        "rationale": _clip(lesson.get("rationale"), 1000),
        "risk": _clip(lesson.get("risk"), 600),
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def rule_fallback_card(game: dict[str, Any]) -> dict[str, Any]:
    """A deterministic lesson when no model key is configured."""

    winner = game.get("winner")
    if winner == "wolf":
        return {
            "title": "狼队优先处理神职",
            "role": "werewolf",
            "phase": "NIGHT_WOLF_KILL",
            "action": "wolf_kill",
            "trigger": "夜晚狼刀阶段仍有神职存活。",
            "recommendation": "夜间优先刀预言家、女巫、猎人，削弱好人技能。",
            "rationale": "神职技能会持续压缩狼队空间，尽早处理收益最大。",
            "risk": "刀错平民可能暴露刀口逻辑，且让神职多活一天。",
        }
    return {
        "title": "好人集中归票",
        "role": "villager",
        "phase": "VOTE",
        "action": "vote",
        "trigger": "白天投票环节，多人观点分散。",
        "recommendation": "投票时集中票数到最可疑目标，避免分票放走狼人。",
        "rationale": "分票会让狼人用少数票反打，集中票能稳定放逐。",
        "risk": "误判时会把好人票出去，需要先在发言阶段统一口径。",
    }


def review_game(
    *,
    game: dict[str, Any],
    actions: Sequence[dict[str, Any]],
    settings: DeepSeekSettings | None = None,
) -> dict[str, Any]:
    """Return a candidate card payload for one finished game."""

    config = settings or DeepSeekSettings.from_environment()
    if not config.api_key:
        return rule_fallback_card(game)

    winner = game.get("winner")
    seed = game.get("seed", 0)
    speech_lines = [
        action.get("content")
        for action in actions
        if action.get("action") in {"speech", "last_words"}
        and isinstance(action.get("content"), str)
    ][-20:]
    system = (
        "你是一个狼人杀复盘教练。根据一局九人局的胜负和过程，总结一条"
        "可复用的战术教训。只输出 JSON，字段：title, role, phase, action, "
        "trigger, recommendation, rationale, risk。role 只能是 "
        "werewolf/villager/seer/witch/hunter；phase 用 VOTE、"
        "NIGHT_WOLF_KILL、NIGHT_SEER_CHECK、NIGHT_WITCH_ACTION、"
        "DAY_DISCUSSION、ANY 之一。不要编造这局没有发生的事。"
    )
    user = (
        f"本局 seed={seed}，胜方是 {winner}。"
        f"对局发言摘录：{' / '.join(speech_lines) if speech_lines else '无'}。"
        f"请针对胜方的一条有效打法，或败方的一条失误，写一条教训。"
    )
    try:
        with httpx.Client(timeout=20.0) as client:
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
                    "response_format": {"type": "json_object"},
                    "temperature": 0.3,
                    "max_tokens": 700,
                },
            )
            response.raise_for_status()
            payload = json.loads(
                response.json()["choices"][0]["message"]["content"]
            )
    except Exception:
        return rule_fallback_card(game)

    required = {
        "title",
        "role",
        "phase",
        "action",
        "trigger",
        "recommendation",
        "rationale",
        "risk",
    }
    if not isinstance(payload, dict) or not required.issubset(payload):
        return rule_fallback_card(game)
    return payload


def card_from_review(
    *,
    game: dict[str, Any],
    actions: Sequence[dict[str, Any]],
    settings: DeepSeekSettings | None = None,
) -> StrategyCard:
    lesson = _sanitize_lesson(
        review_game(game=game, actions=actions, settings=settings)
    )
    seed = game.get("seed", 0)
    winner = game.get("winner", "unknown")
    digest = hashlib.sha1(f"{seed}:{winner}".encode()).hexdigest()[:8]
    return StrategyCard(
        schema_version=1,
        strategy_id=f"cand.review.{digest}",
        title=lesson["title"],
        role=lesson["role"],
        phase=lesson["phase"],
        action=lesson["action"],
        trigger=lesson["trigger"],
        recommendation=lesson["recommendation"],
        rationale=lesson["rationale"],
        risk=lesson["risk"],
        evidence_level="untested",
        source_type="agent_observation",
        source=f"对局复盘 seed={seed} 胜方={winner}",
        status="candidate",
        created_by="ai",
        created_at="2026-11-05T00:00:00+08:00",
    )


def review_run(
    run_directory: Path,
    *,
    strategy_root: Path | None = None,
    settings: DeepSeekSettings | None = None,
) -> list[Path]:
    """Review every finished game in a simulator run and write candidate cards."""

    games = _read_jsonl(run_directory / "games.jsonl")
    actions = _read_jsonl(run_directory / "actions.jsonl")
    library = StrategyLibrary(
        strategy_root or (PROJECT_ROOT / "strategy_library")
    )
    written: list[Path] = []
    for game in games:
        if game.get("status") != "completed":
            continue
        seed = game.get("seed")
        game_actions = [
            action
            for action in actions
            if action.get("seed") == seed
        ]
        card = card_from_review(
            game=game,
            actions=game_actions,
            settings=settings,
        )
        written.append(library.record_candidate(card))
    return written


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("用法：python -m backend.review <run_directory>")
        raise SystemExit(2)
    for path in review_run(Path(sys.argv[1])):
        print(path)
