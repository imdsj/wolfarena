"""Tests for the AI-only simulator and its machine-readable logs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from backend.simulator import (
    SimulationConfig,
    compute_metrics,
    run_simulation,
    simulate_game,
)


class SimulatorGameTests(TestCase):
    def test_same_seed_produces_identical_actions_and_result(self) -> None:
        first_summary, first_actions = simulate_game(
            seed=1033,
            policy_name="l0",
            max_action_steps=600,
            max_days=20,
        )
        second_summary, second_actions = simulate_game(
            seed=1033,
            policy_name="l0",
            max_action_steps=600,
            max_days=20,
        )

        def action_signature(records):
            return [
                (
                    record["step"],
                    record["day"],
                    record["phase"],
                    record["actor_id"],
                    record["actor_role"],
                    record["legal_actions"],
                    record["action"],
                    record["target_id"],
                    record["choice"],
                    record["content"],
                    record["succeeded"],
                    record["phase_after"],
                    record["event_seq_after"],
                )
                for record in records
            ]

        self.assertEqual(action_signature(first_actions), action_signature(second_actions))
        self.assertEqual(
            {
                key: first_summary[key]
                for key in (
                    "status",
                    "terminal_phase",
                    "winner",
                    "action_steps",
                    "day",
                    "roles",
                    "alive_player_ids",
                )
            },
            {
                key: second_summary[key]
                for key in (
                    "status",
                    "terminal_phase",
                    "winner",
                    "action_steps",
                    "day",
                    "roles",
                    "alive_player_ids",
                )
            },
        )

    def test_all_logged_actions_are_legal_and_complete_roles(self) -> None:
        summary, actions = simulate_game(
            seed=1033,
            policy_name="l0",
            max_action_steps=600,
            max_days=20,
        )

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["terminal_phase"], "END")
        self.assertIn(summary["winner"], {"good", "wolf"})
        self.assertTrue(actions)
        self.assertTrue(all(record["succeeded"] for record in actions))
        self.assertTrue(
            all(
                record["action"] in record["legal_actions"]
                for record in actions
            )
        )
        self.assertIn("day_hunter_shot", {record["action"] for record in actions})
        self.assertTrue(
            all(record["phase_after"] for record in actions)
        )

    def test_action_step_limit_records_explicit_error(self) -> None:
        summary, actions = simulate_game(
            seed=1000,
            policy_name="l0",
            max_action_steps=1,
            max_days=20,
        )

        self.assertEqual(summary["status"], "error")
        self.assertEqual(summary["error"]["type"], "max_action_steps")
        self.assertEqual(len(actions), 1)
        self.assertTrue(actions[0]["succeeded"])

    def test_day_limit_records_explicit_error(self) -> None:
        summary, _actions = simulate_game(
            seed=1000,
            policy_name="l0",
            max_action_steps=600,
            max_days=1,
        )

        self.assertEqual(summary["status"], "error")
        self.assertEqual(summary["error"]["type"], "max_days")

    def test_unchanged_state_is_recorded_as_deadlock(self) -> None:
        with patch(
            "backend.simulator.execute_engine_action",
            return_value=None,
        ):
            summary, actions = simulate_game(
                seed=1000,
                policy_name="l0",
                max_action_steps=10,
                max_days=20,
            )

        self.assertEqual(summary["status"], "error")
        self.assertEqual(summary["error"]["type"], "state_not_advanced")
        self.assertEqual(len(actions), 1)

    def test_action_exception_is_logged_and_stops_game(self) -> None:
        with patch(
            "backend.simulator.execute_engine_action",
            side_effect=RuntimeError("模拟动作异常"),
        ):
            summary, actions = simulate_game(
                seed=1000,
                policy_name="l0",
                max_action_steps=10,
                max_days=20,
            )

        self.assertEqual(summary["status"], "error")
        self.assertEqual(summary["error"]["type"], "action_exception")
        self.assertEqual(len(actions), 1)
        self.assertFalse(actions[0]["succeeded"])
        self.assertIn("模拟动作异常", actions[0]["error"])


class SimulatorOutputTests(TestCase):
    def test_run_writes_jsonl_and_recomputable_summary(self) -> None:
        test_root = Path(__file__).resolve().parent.parent / "training_runs"
        output = test_root / "test-simulator-output"
        config = SimulationConfig(
            games=2,
            seed_start=1000,
            policy="l0",
            output_directory=output,
        )
        run_summary = run_simulation(config)

        self.assertEqual(run_summary["summary"]["games_completed"], 2)
        self.assertEqual(run_summary["summary"]["games_failed"], 0)
        self.assertTrue((output / "run.json").is_file())
        self.assertTrue((output / "games.jsonl").is_file())
        self.assertTrue((output / "actions.jsonl").is_file())
        self.assertTrue((output / "roles.json").is_file())
        self.assertTrue((output / "summary.json").is_file())
        self.assertTrue((output / "manifest.json").is_file())

        games = [
            json.loads(line)
            for line in (output / "games.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        actions = [
            json.loads(line)
            for line in (output / "actions.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        roles = json.loads((output / "roles.json").read_text(encoding="utf-8"))
        summary = json.loads(
            (output / "summary.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (output / "manifest.json").read_text(encoding="utf-8")
        )

        self.assertEqual(len(games), 2)
        self.assertEqual(len(roles), 18)
        self.assertEqual(len(actions), run_summary["summary"]["action_steps"])
        self.assertEqual(summary["completion_rate"], 1.0)
        self.assertEqual(summary["action_legal_rate"], 1.0)
        self.assertEqual(
            summary["faction_win_counts"]["good"]
            + summary["faction_win_counts"]["wolf"],
            2,
        )
        self.assertEqual(manifest["hash_algorithm"], "sha256")
        self.assertEqual(
            set(manifest["files"]),
            {
                "run.json",
                "games.jsonl",
                "actions.jsonl",
                "roles.json",
                "summary.json",
            },
        )
        self.assertTrue(all(game["status"] == "completed" for game in games))
        self.assertTrue(all("days" in game and "steps" in game for game in games))
        for record in actions:
            self.assertEqual(
                {
                    "game_id",
                    "seed",
                    "policy",
                    "step",
                    "day",
                    "phase",
                    "actor_id",
                    "actor",
                    "role",
                    "actor_role",
                    "legal_actions",
                    "action",
                    "target",
                    "ok",
                    "succeeded",
                }
                - record.keys(),
                set(),
            )

    def test_metrics_keep_failed_games_out_of_win_rate_denominator(self) -> None:
        games = [
            {
                "status": "completed",
                "terminal_phase": "END",
                "winner": "good",
                "error": None,
                "duration_ms": 10.0,
                "steps": 10,
            },
            {
                "status": "completed",
                "terminal_phase": "END",
                "winner": "wolf",
                "error": None,
                "duration_ms": 20.0,
                "steps": 20,
            },
            {
                "status": "error",
                "terminal_phase": "VOTE",
                "winner": None,
                "error": {"type": "max_days"},
                "duration_ms": 30.0,
                "steps": 30,
            },
        ]
        actions = [
            {"action": "vote", "ok": True},
            {"action": "vote", "ok": True},
            {"action": "wolf_kill", "ok": False},
        ]

        metrics = compute_metrics(
            games,
            actions,
            policy="l0",
            seed_start=1,
            seed_end=3,
        )

        self.assertEqual(metrics["completion_rate"], 2 / 3)
        self.assertEqual(metrics["action_legal_rate"], 2 / 3)
        self.assertEqual(
            metrics["faction_win_rates"],
            {"good": 0.5, "wolf": 0.5},
        )
        self.assertEqual(metrics["errors_by_type"], {"max_days": 1})
        self.assertEqual(metrics["action_frequency_per_game"]["vote"], 2 / 3)

    def test_unknown_policy_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SimulationConfig(
                games=1,
                seed_start=1,
                policy="unknown",
                output_directory=Path("unused"),
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
