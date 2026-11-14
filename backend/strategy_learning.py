"""Web-visible, evidence-backed AI strategy learning.

One click runs a real AI-only game, asks the existing reviewer for a lesson,
and stores that lesson as an unevaluated candidate. The raw game and action
logs stay beside the learning receipt so the growth timeline can always be
traced back to a real seed and replay hash.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from .ai_provider import DeepSeekSettings
from .review import card_from_review
from .simulator import simulate_game
from .strategy_admin import _card_summary
from .strategy_library import StrategyLibrary
from .tactic_policy import DirectivePolicy, load_validated_directives


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEARNING_ROOT = PROJECT_ROOT / "training_runs" / "web-learning"


def learn_one_game(
    seed: int,
    *,
    strategy_root: Path,
    learning_root: Path | None = None,
    settings: DeepSeekSettings | None = None,
) -> dict[str, Any]:
    """Run and review one real game, then return its candidate and receipt."""

    cards = load_validated_directives(strategy_root)
    policy = DirectivePolicy(seed=seed, cards=cards)
    game, actions = simulate_game(
        seed=seed,
        policy_name="l1",
        max_action_steps=600,
        max_days=20,
        policy=policy,
    )
    if game.get("status") != "completed":
        raise ValueError(f"自对弈未完成：{game.get('error')}")

    card = card_from_review(
        game=game,
        actions=actions,
        settings=settings,
    )
    StrategyLibrary(strategy_root).record_candidate(card)
    generation_source = next(
        (
            tag.split(":", 1)[1]
            for tag in card.tags
            if tag.startswith("generation:")
        ),
        "rule_fallback",
    )
    receipt = {
        "seed": seed,
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": game["policy"],
        "validated_tactics_in_play": [item.strategy_id for item in cards],
        "winner": game["winner"],
        "days": game["day"],
        "action_steps": game["action_steps"],
        "replay_sha256": game["replay_sha256"],
        "generation_source": generation_source,
        "strategy_id": card.strategy_id,
        "title": card.title,
    }
    root = learning_root or DEFAULT_LEARNING_ROOT
    run_dir = root / f"seed-{seed}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "game.json").write_text(
        json.dumps(game, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (run_dir / "actions.jsonl").write_text(
        "".join(
            json.dumps(action, ensure_ascii=False) + "\n"
            for action in actions
        ),
        encoding="utf-8",
    )
    (run_dir / "learning.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "receipt": receipt,
        "card": _card_summary(card),
        "evidence_path": f"training_runs/web-learning/seed-{seed}",
    }


def learning_history(
    *,
    learning_root: Path | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Read actual learning receipts, newest first; never invent history."""

    root = learning_root or DEFAULT_LEARNING_ROOT
    receipts: list[dict[str, Any]] = []
    for path in root.glob("seed-*/learning.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("seed") is not None:
            receipts.append(payload)
    receipts.sort(
        key=lambda item: str(item.get("generated_at") or ""),
        reverse=True,
    )
    return receipts[:limit]


__all__ = ["DEFAULT_LEARNING_ROOT", "learn_one_game", "learning_history"]
