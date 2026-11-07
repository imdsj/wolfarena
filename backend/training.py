"""Training-ground skeleton: model registry, metrics and win-rate rollout.

No real L3 training happens here. The registry lists the four fixed models,
the metrics endpoint serves the frozen 200-game evidence, and the rollout
algorithm runs deterministic full games to estimate faction win rates with a
binomial confidence interval. The per-action rollout extension is documented
but not wired, and the win-rate UI is intentionally not built yet.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from .simulator import simulate_game

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "evidence"
MODELS_DIR = PROJECT_ROOT / "strategy_library" / "models"

TRAINING_MODELS: dict[str, dict[str, str]] = {
    "l0.random.v1": {
        "policy": "l0",
        "strategy_id": "l0.random.v1",
        "description": "随机基线，仅用于对照",
        "status": "baseline",
    },
    "l1.rules.v1": {
        "policy": "l1",
        "strategy_id": "l1.rules.v1",
        "description": "人工规则策略",
        "status": "baseline",
    },
    "l2.qtable.v1": {
        "policy": "l2",
        "strategy_id": "l2.qtable.v1",
        "description": "四维状态 Q 表",
        "status": "no_go",
    },
    "l2.qtable.v2": {
        "policy": "l2",
        "strategy_id": "l2.qtable.v2",
        "description": "扩展状态 Q 表",
        "status": "no_go",
    },
}

METRIC_FILES: dict[str, str] = {
    "l0.random.v1": "2026-11-07_l0-200_summary.json",
    "l1.rules.v1": "2026-11-07_l1-200_summary.json",
    "l2.qtable.v1": "2026-11-07_l2-200_summary.json",
    "l2.qtable.v2": "2026-11-07_l2-v2-200_summary.json",
}


class TrainingToolError(ValueError):
    """Raised when a training endpoint receives an invalid argument."""


def wilson_interval(wins: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Two-sided binomial (Wilson) confidence interval."""

    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    margin = (
        z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    )
    return (max(0.0, center - margin), min(1.0, center + margin))


def training_models() -> list[dict[str, str]]:
    return [
        {
            "model_id": model_id,
            "policy": spec["policy"],
            "strategy_id": spec["strategy_id"],
            "description": spec["description"],
            "status": spec["status"],
        }
        for model_id, spec in TRAINING_MODELS.items()
    ]


def training_metrics() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model_id, filename in METRIC_FILES.items():
        path = EVIDENCE_DIR / filename
        summary = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "model_id": model_id,
                "policy": summary["policy"],
                "policy_version": summary.get("policy_version"),
                "seed_start": summary["seed_start"],
                "seed_end": summary["seed_end"],
                "samples": summary["valid_completed_games"],
                "good_wins": summary["faction_win_counts"]["good"],
                "wolf_wins": summary["faction_win_counts"]["wolf"],
                "good_win_rate": summary["faction_win_rates"]["good"],
                "action_legal_rate": summary["action_legal_rate"],
                "code_commit": summary["code_commit"],
                "no_go": model_id.startswith("l2."),
            }
        )
    return rows


def _run_policy_seeds(
    policy: str,
    seed_start: int,
    games: int,
    model_path: Path | None,
) -> tuple[int, int, list[str | None]]:
    # Evaluation must be deterministic and cheap: never call the speech LLM
    # inside a rollout. Restore the flag afterwards.
    previous_speech = os.environ.get("WOLFARENA_LLM_SPEECH")
    os.environ["WOLFARENA_LLM_SPEECH"] = "0"
    learner = None
    try:
        if policy == "l2":
            from .q_policy import QTablePolicy

            path = model_path or (MODELS_DIR / "l2-qtable-v2.json")
            learner = QTablePolicy.load(path)
            learner.freeze()

        good = 0
        wolf = 0
        winners: list[str | None] = []
        for seed in range(seed_start, seed_start + games):
            summary, _actions = simulate_game(
                seed=seed,
                policy_name=policy,
                max_action_steps=600,
                max_days=20,
                policy=learner,
            )
            winner = summary.get("winner")
            if winner == "good":
                good += 1
            elif winner == "wolf":
                wolf += 1
            winners.append(winner)
        return good, wolf, winners
    finally:
        if previous_speech is None:
            os.environ.pop("WOLFARENA_LLM_SPEECH", None)
        else:
            os.environ["WOLFARENA_LLM_SPEECH"] = previous_speech


def rollout_faction_win_rates(
    *,
    policy: str,
    seed_start: int,
    games: int,
    model_path: Path | None = None,
    baseline_policy: str = "l0",
) -> dict[str, object]:
    if policy not in {"l0", "l1", "l2"}:
        raise TrainingToolError(f"未知策略：{policy}")
    if baseline_policy not in {"l0", "l1"}:
        raise TrainingToolError(f"未知基线：{baseline_policy}")
    if isinstance(seed_start, bool) or not isinstance(seed_start, int) or seed_start < 0:
        raise TrainingToolError("seed_start 必须是大于等于 0 的整数")
    if isinstance(games, bool) or not isinstance(games, int) or not 1 <= games <= 100:
        raise TrainingToolError("games 必须在 1 到 100 之间")

    good, wolf, winners = _run_policy_seeds(
        policy, seed_start, games, model_path
    )
    base_good, base_wolf, _ = _run_policy_seeds(
        baseline_policy, seed_start, games, None
    )
    n = games
    good_rate = good / n
    base_rate = base_good / n
    low, high = wilson_interval(good, n)
    return {
        "policy": policy,
        "baseline_policy": baseline_policy,
        "seed_start": seed_start,
        "seed_end": seed_start + games - 1,
        "games": games,
        "good_wins": good,
        "wolf_wins": wolf,
        "good_win_rate": round(good_rate, 4),
        "confidence_interval_95": [round(low, 4), round(high, 4)],
        "baseline_good_win_rate": round(base_rate, 4),
        "delta_good_win_rate": round(good_rate - base_rate, 4),
        "winners": winners,
    }
