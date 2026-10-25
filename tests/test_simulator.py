"""Tests for the AI-only simulator and its machine-readable logs."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

from backend.simulator import SimulationConfig, run_simulation, simulate_game


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

        self.assertEqual(len(games), 2)
        self.assertEqual(len(actions), run_summary["summary"]["action_steps"])
        self.assertTrue(all(game["status"] == "completed" for game in games))
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
                    "actor_role",
                    "legal_actions",
                    "action",
                    "succeeded",
                }
                - record.keys(),
                set(),
            )

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
