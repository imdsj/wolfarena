"""Tests for AI growth records and the L0 policy."""

from unittest import TestCase

from backend.ai_growth import (
    GROWTH_STAGE_ORDER,
    DecisionRecord,
    GrowthStage,
    L0Policy,
    StrategyRecord,
)
from backend.game_engine import Phase, Role


class GrowthStageTests(TestCase):
    def test_growth_stage_order_and_values_are_stable(self) -> None:
        expected = (
            GrowthStage.L0_NOVICE,
            GrowthStage.L1_RULE,
            GrowthStage.L2_STRATEGY,
            GrowthStage.L3_ADVERSARIAL,
        )

        self.assertEqual(GROWTH_STAGE_ORDER, expected)
        self.assertEqual(tuple(GrowthStage), expected)
        self.assertEqual(
            len(GrowthStage),
            len({stage.value for stage in GrowthStage}),
        )


class DecisionRecordTests(TestCase):
    def test_valid_decision_keeps_all_audit_fields(self) -> None:
        record = DecisionRecord(
            game_id="game-001",
            seed=101,
            day=1,
            phase=Phase.NIGHT_WOLF_KILL,
            player_id="p1",
            role=Role.WEREWOLF,
            legal_actions=["p4", "p5", "empty"],
            chosen_action="p4",
            strategy_id="l0.random.v1",
            confidence=0.0,
        )

        self.assertEqual(record.legal_actions, ("p4", "p5", "empty"))
        self.assertEqual(record.chosen_action, "p4")
        self.assertEqual(record.phase, Phase.NIGHT_WOLF_KILL)
        self.assertEqual(record.role, Role.WEREWOLF)
        self.assertIsNone(record.outcome)
        self.assertIsNone(record.reflection)

    def test_chosen_action_must_come_from_legal_actions(self) -> None:
        with self.assertRaises(ValueError):
            DecisionRecord(
                game_id="game-002",
                seed=102,
                day=1,
                phase=Phase.NIGHT_WOLF_KILL,
                player_id="p1",
                role=Role.WEREWOLF,
                legal_actions=("p4",),
                chosen_action="p5",
                strategy_id="l0.random.v1",
                confidence=0.0,
            )

    def test_empty_or_duplicate_legal_actions_are_rejected(self) -> None:
        common = {
            "game_id": "game-003",
            "seed": 103,
            "day": 1,
            "phase": Phase.NIGHT_WOLF_KILL,
            "player_id": "p1",
            "role": Role.WEREWOLF,
            "chosen_action": "p4",
            "strategy_id": "l0.random.v1",
            "confidence": 0.0,
        }
        with self.assertRaises(ValueError):
            DecisionRecord(legal_actions=(), **common)
        with self.assertRaises(ValueError):
            DecisionRecord(legal_actions=("p4", "p4"), **common)

    def test_invalid_confidence_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DecisionRecord(
                game_id="game-004",
                seed=104,
                day=1,
                phase=Phase.NIGHT_WOLF_KILL,
                player_id="p1",
                role=Role.WEREWOLF,
                legal_actions=("p4",),
                chosen_action="p4",
                strategy_id="l0.random.v1",
                confidence=1.1,
            )


class StrategyRecordTests(TestCase):
    def test_new_strategy_has_no_fabricated_metrics(self) -> None:
        record = StrategyRecord(
            strategy_id="wolf.random.v1",
            role=Role.WEREWOLF,
            phase=Phase.NIGHT_WOLF_KILL,
            trigger="first_night",
            action="kill",
            source="L0 baseline",
        )

        self.assertEqual(record.samples, 0)
        self.assertIsNone(record.win_rate)
        self.assertIsNone(record.interval)
        self.assertEqual(record.version, "v0.1")
        self.assertEqual(record.status, "untested")

    def test_win_rate_without_samples_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            StrategyRecord(
                strategy_id="fake",
                role=Role.WEREWOLF,
                phase=Phase.NIGHT_WOLF_KILL,
                trigger="first_night",
                action="kill",
                source="test",
                samples=0,
                win_rate=0.5,
            )

    def test_interval_requires_real_samples_and_win_rate(self) -> None:
        with self.assertRaises(ValueError):
            StrategyRecord(
                strategy_id="fake-interval",
                role=Role.WEREWOLF,
                phase=Phase.NIGHT_WOLF_KILL,
                trigger="first_night",
                action="kill",
                source="test",
                interval=(0.45, 0.55),
            )

    def test_measured_strategy_accepts_valid_metrics(self) -> None:
        record = StrategyRecord(
            strategy_id="wolf.measured.v1",
            role=Role.WEREWOLF,
            phase=Phase.NIGHT_WOLF_KILL,
            trigger="first_night",
            action="kill",
            source="fixed-seed simulation",
            samples=200,
            win_rate=0.52,
            interval=(0.45, 0.59),
            status="measured",
        )

        self.assertEqual(record.samples, 200)
        self.assertEqual(record.win_rate, 0.52)
        self.assertEqual(record.interval, (0.45, 0.59))


class L0PolicyTests(TestCase):
    def test_same_seed_produces_same_decision_sequence(self) -> None:
        actions = ("p4", "p5", "p6", "empty")
        first = L0Policy(seed=20261023)
        second = L0Policy(seed=20261023)

        first_sequence = [first.choose_action(actions) for _ in range(30)]
        second_sequence = [second.choose_action(actions) for _ in range(30)]

        self.assertEqual(first_sequence, second_sequence)
        self.assertTrue(set(first_sequence) <= set(actions))

    def test_every_choice_comes_from_legal_actions(self) -> None:
        policy = L0Policy(seed=7)
        legal_actions = ("save", "poison", "none")

        for _ in range(100):
            self.assertIn(policy.choose_action(legal_actions), legal_actions)

    def test_empty_legal_actions_are_rejected(self) -> None:
        policy = L0Policy(seed=8)
        with self.assertRaises(ValueError):
            policy.choose_action(())

    def test_duplicate_or_blank_actions_are_rejected(self) -> None:
        policy = L0Policy(seed=9)
        with self.assertRaises(ValueError):
            policy.choose_action(("p1", "p1"))
        with self.assertRaises(ValueError):
            policy.choose_action(("p1", " "))

    def test_make_decision_records_l0_metadata(self) -> None:
        policy = L0Policy(seed=10)
        record = policy.make_decision(
            game_id="game-010",
            day=1,
            phase=Phase.NIGHT_WITCH_ACTION,
            player_id="p8",
            role=Role.WITCH,
            legal_actions=("save", "poison", "none"),
        )

        self.assertIn(record.chosen_action, record.legal_actions)
        self.assertEqual(record.seed, 10)
        self.assertEqual(record.strategy_id, "l0.random.v1")
        self.assertEqual(record.confidence, 0.0)
        self.assertIsNone(record.outcome)
        self.assertIsNone(record.reflection)

    def test_l0_policy_rejects_non_novice_stage(self) -> None:
        with self.assertRaises(ValueError):
            L0Policy(seed=11, stage=GrowthStage.L2_STRATEGY)
