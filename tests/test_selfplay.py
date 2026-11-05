"""Tests for the AI-vs-AI self-play loop."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from backend.selfplay import run_selfplay


class SelfplayTests(TestCase):
    def test_one_round_reviews_games_into_candidates(self) -> None:
        base = Path("training_runs") / f"test-selfplay-{uuid4().hex}"
        produced = run_selfplay(
            rounds=1,
            games_per_round=2,
            seed_start=5000,
            policy="l1",
            out_root=base / "runs",
            strategy_root=base / "strategy",
        )
        self.assertEqual(len(produced), 2)
        for path in produced:
            self.assertTrue(path.exists())
            self.assertEqual(path.parent.name, "candidates")

    def test_rejects_unsupported_policy(self) -> None:
        base = Path("training_runs") / f"test-selfplay-{uuid4().hex}"
        with self.assertRaises(ValueError):
            run_selfplay(
                rounds=1,
                games_per_round=1,
                seed_start=6000,
                policy="l2",
                out_root=base / "runs",
                strategy_root=base / "strategy",
            )
