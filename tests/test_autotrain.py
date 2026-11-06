"""Smoke tests for the resumable nightly self-play loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from backend.ai_provider import DeepSeekSettings
from backend.autotrain import run_autotrain
from backend.strategy_library import StrategyLibrary


class AutoTrainSmokeTests(TestCase):
    def setUp(self) -> None:
        self.base = Path("training_runs") / f"test-autotrain-{uuid4().hex}"
        self.strategy = self.base / "strategy"

    def test_offline_round_advances_seed_and_writes_report(self) -> None:
        summary = run_autotrain(
            out_root=self.base / "run",
            strategy_root=self.strategy,
            hours=0.02,
            budget_cny=1.0,
            rounds=1,
            games_per_round=2,
            review_limit=0,
            eval_games=2,
            seed_start=50000,
            settings=DeepSeekSettings(api_key=None),
        )
        self.assertEqual(summary["rounds"], 1)
        state = json.loads((self.base / "run" / "state.json").read_text("utf-8"))
        self.assertEqual(state["next_seed"], 50002)
        self.assertTrue((self.base / "run" / "report.md").is_file())
        counts = StrategyLibrary(self.strategy).counts()
        self.assertEqual(counts["validated"], 0)

    def test_second_round_resumes_from_saved_seed(self) -> None:
        kwargs = dict(
            out_root=self.base / "run2",
            strategy_root=self.strategy,
            hours=0.02,
            budget_cny=1.0,
            rounds=1,
            games_per_round=1,
            review_limit=0,
            eval_games=2,
            settings=DeepSeekSettings(api_key=None),
        )
        run_autotrain(seed_start=60000, **kwargs)
        run_autotrain(seed_start=60000, **kwargs)
        state = json.loads((self.base / "run2" / "state.json").read_text("utf-8"))
        self.assertEqual(state["next_seed"], 60002)
        self.assertEqual(state["rounds_done"], 2)
