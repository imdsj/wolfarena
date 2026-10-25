"""Recompute simulator metrics independently from exported JSONL logs."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def recompute_metrics(run_directory: Path) -> dict[str, Any]:
    """Calculate all public metrics from games.jsonl and actions.jsonl."""

    games = _read_jsonl(run_directory / "games.jsonl")
    actions = _read_jsonl(run_directory / "actions.jsonl")
    total_games = len(games)
    completed = [
        game
        for game in games
        if game.get("status") == "completed"
        and game.get("terminal_phase") == "END"
    ]
    valid = [
        game for game in completed if game.get("winner") in {"good", "wolf"}
    ]
    successes = sum(action.get("ok") is True for action in actions)
    action_counts = Counter(
        action["action"] for action in actions if action.get("ok") is True
    )
    wins = Counter(game["winner"] for game in valid)
    errors = Counter(
        game["error"].get("type")
        for game in games
        if game.get("status") != "completed"
        and isinstance(game.get("error"), dict)
        and game["error"].get("type")
    )
    valid_count = len(valid)
    durations = [float(game["duration_ms"]) for game in completed]
    steps = [int(game["steps"]) for game in completed]

    return {
        "total_games": total_games,
        "completed_games": len(completed),
        "valid_completed_games": valid_count,
        "failed_games": total_games - len(completed),
        "completion_rate": len(completed) / total_games if total_games else None,
        "actions_submitted": len(actions),
        "actions_succeeded": successes,
        "actions_failed": len(actions) - successes,
        "action_legal_rate": successes / len(actions) if actions else None,
        "action_counts": dict(sorted(action_counts.items())),
        "action_frequency_per_game": {
            action: count / total_games
            for action, count in sorted(action_counts.items())
        }
        if total_games
        else {},
        "faction_win_counts": {
            "good": wins["good"],
            "wolf": wins["wolf"],
        },
        "faction_win_rates": {
            "good": wins["good"] / valid_count if valid_count else None,
            "wolf": wins["wolf"] / valid_count if valid_count else None,
        },
        "average_steps": sum(steps) / len(steps) if steps else None,
        "average_duration_ms": (
            sum(durations) / len(durations) if durations else None
        ),
        "total_duration_ms": sum(durations),
        "errors_by_type": dict(sorted(errors.items())),
    }


def _differences(
    expected: Any,
    actual: Any,
    *,
    path: str = "",
) -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}" if path else key
            if key not in expected or key not in actual:
                differences.append(f"{child}: missing")
            else:
                differences.extend(
                    _differences(expected[key], actual[key], path=child)
                )
        return differences
    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(actual, (int, float))
        and not isinstance(actual, bool)
    ):
        return (
            []
            if math.isclose(
                float(expected),
                float(actual),
                rel_tol=1e-12,
                abs_tol=1e-9,
            )
            else [f"{path}: {expected!r} != {actual!r}"]
        )
    return [] if expected == actual else [f"{path}: {expected!r} != {actual!r}"]


def verify_summary(
    metrics: dict[str, Any],
    summary: dict[str, Any],
) -> list[str]:
    """Return differences for fields present in both calculations."""

    expected = {
        key: value
        for key, value in summary.items()
        if key in metrics
    }
    actual = {
        key: metrics[key]
        for key in expected
    }
    return _differences(expected, actual)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recompute WolfArena simulator metrics from JSONL",
    )
    parser.add_argument(
        "--run",
        type=Path,
        required=True,
        help="包含 games.jsonl 与 actions.jsonl 的运行目录",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="可选重算结果路径，默认写入运行目录 recomputed-summary.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_directory: Path = args.run
    try:
        metrics = recompute_metrics(run_directory)
        summary_path = run_directory / "summary.json"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.is_file()
            else {}
        )
        differences = verify_summary(metrics, summary)
        output_path = args.out or run_directory / "recomputed-summary.json"
        payload = {
            "run_directory": str(run_directory),
            "metrics": metrics,
            "matches_summary": not differences,
            "differences": differences,
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not differences else 1


if __name__ == "__main__":
    sys.exit(main())
