"""Continuous AI-vs-AI self-play with automatic post-game review.

Each round runs a batch of AI-only games and immediately reviews them into
candidate strategy cards. Candidates never enter the retrieval set by
themselves: promotion still needs 200-game evidence plus a human sign-off.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .review import review_run
from .simulator import SimulationConfig, run_simulation

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_selfplay(
    *,
    rounds: int,
    games_per_round: int,
    seed_start: int,
    policy: str = "l1",
    out_root: Path,
    strategy_root: Path | None = None,
    review: bool = True,
) -> list[Path]:
    """Run ``rounds`` batches of AI-only games, reviewing each batch."""

    if rounds <= 0 or games_per_round <= 0:
        raise ValueError("rounds 和 games 必须大于 0")
    if policy not in {"l0", "l1"}:
        raise ValueError("自对弈循环只支持 l0 / l1")

    produced: list[Path] = []
    for round_index in range(rounds):
        round_seed = seed_start + round_index * games_per_round
        run_dir = out_root / f"round-{round_index + 1:02d}"
        run_simulation(
            SimulationConfig(
                games=games_per_round,
                seed_start=round_seed,
                policy=policy,
                output_directory=run_dir,
                code_commit="selfplay",
            )
        )
        if review:
            produced.extend(review_run(run_dir, strategy_root=strategy_root))
        print(
            f"round {round_index + 1}: games={games_per_round} "
            f"seeds={round_seed}-{round_seed + games_per_round - 1} "
            f"candidates={len(produced)}"
        )
    return produced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WolfArena 自对弈循环")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=5000)
    parser.add_argument("--policy", choices=["l0", "l1"], default="l1")
    parser.add_argument("--out", type=Path, default=Path("training_runs/selfplay"))
    parser.add_argument("--no-review", action="store_true")
    args = parser.parse_args(argv)
    run_selfplay(
        rounds=args.rounds,
        games_per_round=args.games,
        seed_start=args.seed_start,
        policy=args.policy,
        out_root=args.out,
        review=not args.no_review,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
