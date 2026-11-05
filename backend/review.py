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
from .directives import DIRECTIVE_ACTIONS, DIRECTIVES
from .llm_budget import LEDGER
from .rulebook import rules_brief
from .strategy_library import (
    STRATEGY_TOOL_PHASES,
    StrategyCard,
    StrategyLibrary,
    StrategyError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALLOWED_ROLES = {"werewolf", "villager", "seer", "witch", "hunter"}

DEFAULT_DIRECTIVE = {
    ("witch", "witch_action"): "witch_poison_most_accused",
    ("hunter", "night_hunter_shot"): "hunter_hold",
    ("hunter", "day_hunter_shot"): "hunter_hold",
    ("seer", "seer_check"): "seer_check_counterclaim",
    ("werewolf", "wolf_kill"): "wolf_kill_accuser",
}


def _clip(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _sanitize_lesson(lesson: dict[str, Any]) -> dict[str, Any]:
    role = lesson.get("role")
    if role not in ALLOWED_ROLES:
        role = "villager"
    phase = lesson.get("phase")
    if phase not in STRATEGY_TOOL_PHASES:
        phase = "ANY"
    action = _clip(lesson.get("action"), 64) or "vote"
    directive = lesson.get("directive")
    if not isinstance(directive, str) or directive not in DIRECTIVES:
        directive = None
    if directive is not None and action not in DIRECTIVE_ACTIONS[directive]:
        directive = None
    if directive is None:
        directive = DEFAULT_DIRECTIVE.get(
            (role, action),
            "vote_most_accused" if action == "vote" else None,
        )
    if directive is not None and action not in DIRECTIVE_ACTIONS[directive]:
        directive = None
    return {
        "title": _clip(lesson.get("title"), 120) or "复盘教训",
        "role": role,
        "phase": phase,
        "action": action,
        "directive": directive,
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
            "directive": "wolf_kill_accuser",
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
        "directive": "vote_most_accused",
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
    timeline = _timeline(game, actions)
    system = (
        "你是一个狼人杀复盘教练。根据一局九人局的真实过程和结果，总结一条"
        "可复用、可执行的战术教训。只输出 JSON，字段：title, role, phase, "
        "action, directive, trigger, recommendation, rationale, risk。"
        "role 只能是 werewolf/villager/seer/witch/hunter；phase 用 VOTE、"
        "NIGHT_WOLF_KILL、NIGHT_SEER_CHECK、NIGHT_WITCH_ACTION、"
        "DAY_DISCUSSION、ANY 之一。"
        "directive 必须从下列机器可执行指令里选一个，并且与 action 匹配：\n"
        "vote_most_accused / vote_reported_wolf / vote_silent（action=vote）；"
        "witch_poison_most_accused / witch_save_only_god（action=witch_action）；"
        "hunter_shoot_most_accused / hunter_hold（action=day_hunter_shot 或 "
        "night_hunter_shot）；seer_check_counterclaim（action=seer_check）；"
        "wolf_kill_accuser（action=wolf_kill）。\n"
        "只总结这一局真实发生的事，不要编造。\n" + rules_brief()
    )
    user = (
        f"本局 seed={seed}，胜方是 {winner}，共 {game.get('day', 0)} 天。"
        f"身份配置：{_roles_text(game)}。"
        f"\n关键过程：\n{timeline}"
        f"对局发言摘录：{' / '.join(speech_lines) if speech_lines else '无'}。"
        "请针对胜方的一条有效打法，或败方的一条可修复失误，写一条能落地的教训。"
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
            body = response.json()
            LEDGER.record(
                source="review",
                usage=body.get("usage"),
                prompt_chars=len(system) + len(user),
                completion_chars=len(
                    str(body["choices"][0]["message"]["content"])
                ),
            )
            payload = json.loads(
                body["choices"][0]["message"]["content"]
            )
    except Exception:
        LEDGER.record_failure()
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


def _seat_from_player_id(player_id: object) -> str:
    if not isinstance(player_id, str):
        return "?"
    digits = "".join(character for character in player_id if character.isdigit())
    return digits or "?"


def _roles_text(game: dict[str, Any]) -> str:
    roles = game.get("roles")
    if not isinstance(roles, dict):
        return "未知"
    seats = sorted(
        (
            int(_seat_from_player_id(player_id))
            if _seat_from_player_id(player_id).isdigit()
            else 0,
            role,
        )
        for player_id, role in roles.items()
    )
    return "，".join(f"{seat}号{role}" for seat, role in seats if seat)


def _timeline(
    game: dict[str, Any],
    actions: Sequence[dict[str, Any]],
    *,
    limit: int = 60,
) -> str:
    """A compact action trail so the reviewer can talk about kills and votes."""

    interesting = {
        "wolf_kill",
        "seer_check",
        "witch_action",
        "vote",
        "speech",
        "last_words",
        "self_destruct",
        "day_hunter_shot",
        "night_hunter_shot",
    }
    lines: list[str] = []
    for action in actions:
        name = action.get("action")
        if name not in interesting or not action.get("ok"):
            continue
        seat = _seat_from_player_id(action.get("actor_id"))
        target = _seat_from_player_id(action.get("target_id"))
        choice = action.get("choice")
        suffix = f"->{target}号" if target != "?" else ""
        if choice:
            suffix += f"[{choice}]"
        content = action.get("content")
        if name in {"speech", "last_words"} and isinstance(content, str):
            suffix += f"：{content[:60]}"
        lines.append(
            f"D{action.get('day', 0)} {action.get('phase')} "
            f"{seat}号 {action.get('actor_role')} {name}{suffix}"
        )
    if len(lines) > limit:
        lines = lines[: limit // 2] + ["..."] + lines[-(limit // 2) :]
    return "\n".join(lines) + "\n" if lines else "无\n"


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
        directive=lesson["directive"],
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
        try:
            written.append(library.record_candidate(card))
        except StrategyError:
            # Reviewing the same game twice yields the same strategy id; the
            # first card already captured it, so skipping is the safe outcome.
            continue
    return written


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("用法：python -m backend.review <run_directory>")
        raise SystemExit(2)
    for path in review_run(Path(sys.argv[1])):
        print(path)
