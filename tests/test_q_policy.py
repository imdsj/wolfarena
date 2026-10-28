"""Tests for the minimal l2.qtable.v1 Q-learning policy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from backend.game_engine import Role, create_game, get_player
from backend.q_policy import (
    QPolicyConfig,
    QTablePolicy,
    STRATEGY_ID,
    alive_bucket,
    day_bucket,
    faction_of,
    state_key,
    visible_key,
)
from backend.simulator import SimulationConfig, run_simulation


def _policy(**overrides) -> QTablePolicy:
    config = QPolicyConfig(seed=overrides.pop("seed", 7), **overrides)
    return QTablePolicy(config)


def _temp_dir(prefix: str) -> Path:
    """Scratch directory under the ignored training_runs folder."""

    root = Path(__file__).resolve().parent.parent / "training_runs"
    path = root / f"test-{prefix}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class VisibilityTests(TestCase):
    def test_other_players_hidden_roles_do_not_change_key(self) -> None:
        state = create_game(seed=11, human_count=0)
        actor = get_player(state, "p1")
        before = visible_key(state, actor)

        for player in state.players:
            if player.player_id != actor.player_id:
                player.role = Role.WEREWOLF

        self.assertEqual(before, visible_key(state, actor))

    def test_own_role_changes_key(self) -> None:
        state = create_game(seed=11, human_count=0)
        actor = get_player(state, "p1")
        before = visible_key(state, actor)
        actor.role = (
            Role.WEREWOLF
            if actor.role is not Role.WEREWOLF
            else Role.VILLAGER
        )
        self.assertNotEqual(before, visible_key(state, actor))

    def test_buckets_cover_every_day_and_alive_count(self) -> None:
        self.assertEqual(day_bucket(1), "d1")
        self.assertEqual(day_bucket(2), "d2-3")
        self.assertEqual(day_bucket(9), "d4+")
        self.assertEqual(alive_bucket(9), "a9")
        self.assertEqual(alive_bucket(8), "a7-8")
        self.assertEqual(alive_bucket(0), "a0-2")
        self.assertEqual(
            state_key(role="villager", phase="VOTE", day=2, alive=6),
            "villager|VOTE|d2-3|a5-6",
        )

    def test_faction_uses_only_werewolf_role(self) -> None:
        self.assertEqual(faction_of(Role.WEREWOLF), "wolf")
        for role in (Role.VILLAGER, Role.SEER, Role.WITCH, Role.HUNTER):
            self.assertEqual(faction_of(role), "good")


class ActionChoiceTests(TestCase):
    def setUp(self) -> None:
        self.state = create_game(seed=5, human_count=0)
        self.actor = get_player(self.state, "p1")

    def test_choose_action_requires_observed_state(self) -> None:
        policy = _policy()
        with self.assertRaises(RuntimeError):
            policy.choose_action(("vote", "speech"))

    def test_choose_action_stays_inside_legal_actions(self) -> None:
        legal = ("wolf_speech", "wolf_kill", "vote", "speech", "seer_check")
        for seed in range(30):
            policy = _policy(seed=seed, epsilon_start=1.0, epsilon_end=1.0)
            policy.observe_state(self.state, self.actor)
            chosen = policy.choose_action(legal)
            self.assertIn(chosen, legal)

    def test_untrained_policy_follows_l1_priority(self) -> None:
        policy = _policy()
        policy.observe_state(self.state, self.actor)
        self.assertEqual(
            policy.choose_action(("vote", "speech", "wolf_speech")),
            "wolf_speech",
        )

    def test_empty_and_duplicate_legal_actions_are_rejected(self) -> None:
        policy = _policy()
        policy.observe_state(self.state, self.actor)
        with self.assertRaises(ValueError):
            policy.choose_action(())
        with self.assertRaises(ValueError):
            policy.choose_action(("vote", "vote"))

    def test_same_seed_repeats_the_same_choices(self) -> None:
        picks = []
        for _ in range(2):
            policy = _policy(seed=3, epsilon_start=1.0, epsilon_end=1.0)
            policy.observe_state(self.state, self.actor)
            picks.append(
                [
                    policy.choose_action(("vote", "speech", "wolf_kill"))
                    for _ in range(20)
                ]
            )
        self.assertEqual(picks[0], picks[1])


class EpsilonTests(TestCase):
    def test_epsilon_decays_from_start_to_end(self) -> None:
        policy = _policy(epsilon_start=0.3, epsilon_end=0.05)
        policy.set_progress(0, 10)
        self.assertAlmostEqual(policy.epsilon, 0.3)
        policy.set_progress(5, 10)
        middle = policy.epsilon
        self.assertLess(middle, 0.3)
        self.assertGreater(middle, 0.05)
        policy.set_progress(10, 10)
        self.assertAlmostEqual(policy.epsilon, 0.05)

    def test_frozen_policy_is_greedy_and_stops_learning(self) -> None:
        state = create_game(seed=5, human_count=0)
        actor = get_player(state, "p1")
        policy = _policy(epsilon_start=1.0, epsilon_end=1.0)
        policy.observe_state(state, actor)
        policy.choose_action(("vote", "speech"))
        digest = policy.freeze()

        self.assertFalse(policy.config.training)
        self.assertEqual(policy.epsilon, 0.0)
        self.assertEqual(policy.meta["frozen_from_hash"], digest)
        table_before = json.dumps(policy.q_table, sort_keys=True)
        policy.end_episode("good")
        self.assertEqual(json.dumps(policy.q_table, sort_keys=True), table_before)


class RewardTests(TestCase):
    def setUp(self) -> None:
        self.state = create_game(seed=5, human_count=0)
        self.actor = get_player(self.state, "p1")

    def test_winning_terminal_reward_is_positive(self) -> None:
        policy = _policy(alpha=0.5, gamma=0.9)
        policy.begin_episode()
        policy.observe_state(self.state, self.actor)
        chosen = policy.choose_action(("vote", "speech"))
        key = visible_key(self.state, self.actor)

        policy.end_episode(faction_of(self.actor.role))

        self.assertGreater(policy.q_table[key][chosen], 0.0)
        self.assertEqual(policy.stats["episodes"], 1)

    def test_losing_terminal_reward_is_negative(self) -> None:
        policy = _policy(alpha=0.5, gamma=0.9)
        policy.begin_episode()
        policy.observe_state(self.state, self.actor)
        chosen = policy.choose_action(("vote", "speech"))
        key = visible_key(self.state, self.actor)
        other = "good" if faction_of(self.actor.role) == "wolf" else "wolf"

        policy.end_episode(other)

        self.assertLess(policy.q_table[key][chosen], 0.0)

    def test_intermediate_steps_carry_zero_reward(self) -> None:
        policy = _policy(alpha=0.5, gamma=0.9)
        policy.begin_episode()
        policy.observe_state(self.state, self.actor)
        chosen = policy.choose_action(("vote", "speech"))
        key = visible_key(self.state, self.actor)

        self.actor.is_alive = True
        policy.observe_state(self.state, self.actor)
        policy.choose_action(("vote", "speech"))

        self.assertEqual(policy.q_table.get(key, {}).get(chosen, 0.0), 0.0)


class PersistenceTests(TestCase):
    def test_save_and_load_roundtrip_preserves_table(self) -> None:
        state = create_game(seed=5, human_count=0)
        actor = get_player(state, "p1")
        policy = _policy()
        policy.begin_episode()
        policy.observe_state(state, actor)
        policy.choose_action(("vote", "speech"))
        policy.end_episode("good")

        path = _temp_dir("q-model") / "model.json"
        digest = policy.save(path)
        loaded = QTablePolicy.load(path)

        self.assertEqual(loaded.content_hash, digest)
        self.assertEqual(loaded.q_table, policy.q_table)
        self.assertEqual(loaded.strategy_id, STRATEGY_ID)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)

    def test_tampered_table_is_rejected(self) -> None:
        policy = _policy()
        path = _temp_dir("q-model-tamper") / "model.json"
        policy.save(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["q_table"] = {"forged": {"vote": 99.0}}
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            QTablePolicy.load(path)


class SimulatorIntegrationTests(TestCase):
    def test_l2_requires_a_model_destination_or_source(self) -> None:
        root = _temp_dir("q-config")
        with self.assertRaises(ValueError):
            SimulationConfig(
                games=1,
                seed_start=0,
                policy="l2",
                output_directory=root / "run",
            )

    def test_training_batch_is_reproducible(self) -> None:
        root = _temp_dir("q-repro")
        hashes = []
        for index in range(2):
            out = root / f"run-{index}"
            run_simulation(
                SimulationConfig(
                    games=1,
                    seed_start=0,
                    policy="l2",
                    output_directory=out,
                    model_out=out / "model.json",
                    code_commit="test-sha",
                )
            )
            manifest = json.loads(
                (out / "manifest.json").read_text(encoding="utf-8")
            )
            hashes.append(
                manifest["files"]["actions.jsonl"]["sha256"]
                + manifest["model"]["content_hash"]
            )
        self.assertEqual(hashes[0], hashes[1])
