"""Independent recomputation tests for simulator metrics."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

from backend.metrics import recompute_metrics, verify_summary


class MetricsRecomputeTests(TestCase):
    def setUp(self) -> None:
        self.output = (
            Path(__file__).resolve().parent.parent
            / "training_runs"
            / "test-metrics-output"
        )
        self.output.mkdir(parents=True, exist_ok=True)
        games = [
            {
                "status": "completed",
                "terminal_phase": "END",
                "winner": "good",
                "duration_ms": 10.0,
                "steps": 10,
                "error": None,
            },
            {
                "status": "completed",
                "terminal_phase": "END",
                "winner": "wolf",
                "duration_ms": 20.0,
                "steps": 20,
                "error": None,
            },
            {
                "status": "error",
                "terminal_phase": "VOTE",
                "winner": None,
                "duration_ms": 30.0,
                "steps": 30,
                "error": {"type": "max_days"},
            },
        ]
        actions = [
            {"action": "vote", "ok": True},
            {"action": "vote", "ok": True},
            {"action": "wolf_kill", "ok": False},
        ]
        (self.output / "games.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in games),
            encoding="utf-8",
        )
        (self.output / "actions.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in actions),
            encoding="utf-8",
        )

    def test_metrics_are_recomputed_from_raw_rows(self) -> None:
        metrics = recompute_metrics(self.output)

        self.assertEqual(metrics["completion_rate"], 2 / 3)
        self.assertEqual(metrics["actions_submitted"], 3)
        self.assertEqual(metrics["actions_succeeded"], 2)
        self.assertEqual(metrics["action_legal_rate"], 2 / 3)
        self.assertEqual(metrics["action_counts"], {"vote": 2})
        self.assertEqual(
            metrics["faction_win_rates"],
            {"good": 0.5, "wolf": 0.5},
        )
        self.assertEqual(metrics["average_steps"], 15.0)
        self.assertEqual(metrics["average_duration_ms"], 15.0)

    def test_saved_summary_mismatch_is_reported(self) -> None:
        metrics = recompute_metrics(self.output)
        expected = {
            **metrics,
            "completion_rate": 1.0,
        }

        differences = verify_summary(metrics, expected)

        self.assertEqual(len(differences), 1)
        self.assertIn("completion_rate", differences[0])


if __name__ == "__main__":
    import unittest

    unittest.main()
