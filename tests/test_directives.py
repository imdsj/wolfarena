"""Tests for public-signal parsing, directives and the tactic policy."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from backend.directives import apply_directive, directive_applies
from backend.game_engine import EventType, Role, Visibility, append_event, create_game
from backend.promote import mcnemar_exact_p
from backend.public_signals import build_signals, parse_speech
from backend.strategy_library import PromotionEvidence, StrategyCard
from backend.tactic_policy import DirectivePolicy


def card(directive: str, role: str, action: str, phase: str = "ANY") -> StrategyCard:
    return StrategyCard(
        strategy_id=f"cand.{directive}.{role}",
        title="测试战术",
        role=role,
        phase=phase,
        action=action,
        directive=directive,
        trigger="测试触发条件",
        recommendation="测试建议",
        rationale="测试理由",
        risk="测试风险",
        source_type="agent_observation",
        source="test",
        status="candidate",
        created_by="ai",
        created_at="2026-11-05T00:00:00+08:00",
    )


class ParseSpeechTests(TestCase):
    def test_extracts_claim_accusation_and_report(self) -> None:
        claims, accusations, reports = parse_speech(
            "我是预言家，我验了5号是狼，大家票5号。"
        )
        self.assertEqual(claims, {"seer"})
        self.assertGreaterEqual(accusations[5], 1)
        self.assertEqual(reports[5], "wolf")

    def test_negated_claim_is_ignored(self) -> None:
        claims, _, _ = parse_speech("我不是预言家，别票我。")
        self.assertEqual(claims, set())

    def test_gift_is_read_as_good(self) -> None:
        _, _, reports = parse_speech("我给6号金水，7号查杀。")
        self.assertEqual(reports[6], "good")
        self.assertEqual(reports[7], "wolf")


class SignalsPrivacyTests(TestCase):
    def test_wolf_channel_is_invisible_to_villager(self) -> None:
        state = create_game(seed=11, human_count=0)
        wolf = next(p for p in state.players if p.role is Role.WEREWOLF)
        villager = next(p for p in state.players if p.role is Role.VILLAGER)
        append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={"content": "我狼队频道说 3 号是狼队友"},
        )
        signals = build_signals(state, villager)
        self.assertEqual(dict(signals.claims), {})
        self.assertEqual(dict(signals.accusations), {})


class DirectivePolicyTests(TestCase):
    def _view(self, state, action: str, choices: list[str] | None = None):
        return SimpleNamespace(
            action=action,
            target_ids=[
                player.player_id for player in state.players if player.is_alive
            ],
            choices=choices or [],
        )

    def test_vote_follows_public_accusations(self) -> None:
        state = create_game(seed=21, human_count=0)
        actor = state.players[0]
        accused = state.players[4]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=state.players[1].player_id,
            data={"content": f"我怀疑{accused.seat}号，大家票{accused.seat}号。"},
        )
        policy = DirectivePolicy(
            seed=21,
            cards=[card("vote_most_accused", actor.role.value, "vote")],
        )
        picked = policy.choose_target(state, actor, self._view(state, "vote"))
        self.assertEqual(picked, accused.player_id)

    def test_falls_back_when_nothing_is_accused(self) -> None:
        state = create_game(seed=22, human_count=0)
        actor = state.players[0]
        policy = DirectivePolicy(
            seed=22,
            cards=[card("vote_most_accused", actor.role.value, "vote")],
        )
        view = self._view(state, "vote")
        self.assertEqual(
            policy.choose_target(state, actor, view),
            view.target_ids[0],
        )

    def test_hunter_can_hold_the_shot(self) -> None:
        state = create_game(seed=23, human_count=0)
        hunter = next(p for p in state.players if p.role is Role.HUNTER)
        policy = DirectivePolicy(
            seed=23,
            cards=[card("hunter_hold", "hunter", "day_hunter_shot")],
        )
        view = self._view(state, "day_hunter_shot")
        self.assertIsNone(policy.choose_target(state, hunter, view))

    def test_witch_skips_antidote_for_unclaimed_victim(self) -> None:
        state = create_game(seed=24, human_count=0)
        witch = next(p for p in state.players if p.role is Role.WITCH)
        policy = DirectivePolicy(
            seed=24,
            cards=[card("witch_save_only_god", "witch", "witch_action")],
        )
        view = self._view(state, "witch_action", ["none", "antidote", "poison"])
        self.assertEqual(policy.choose_choice(state, witch, view), "none")

    def test_directive_is_bound_to_its_action(self) -> None:
        self.assertTrue(directive_applies("vote_most_accused", "vote"))
        self.assertFalse(directive_applies("vote_most_accused", "seer_check"))


class CardValidationTests(TestCase):
    def test_unknown_directive_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            StrategyCard(
                strategy_id="cand.bad.directive",
                title="坏卡",
                role="villager",
                phase="VOTE",
                action="vote",
                directive="delete_database",
                trigger="t",
                recommendation="r",
                rationale="r",
                risk="r",
                source_type="agent_observation",
                source="test",
                status="candidate",
                created_by="ai",
                created_at="2026-11-05T00:00:00+08:00",
            )

    def test_mismatched_directive_action_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            card("witch_poison_most_accused", "villager", "vote")


class GateMathTests(TestCase):
    def test_mcnemar_matches_known_values(self) -> None:
        self.assertEqual(mcnemar_exact_p(0, 0), 1.0)
        # 10 vs 0 discordant pairs: 2 * 1/1024
        self.assertAlmostEqual(mcnemar_exact_p(10, 0), 0.001953125)
        self.assertGreater(mcnemar_exact_p(5, 5), 0.9)

    def test_auto_gate_cannot_impersonate_human(self) -> None:
        payload = {
            "reviewer": "auto-gate.v1",
            "approved": True,
            "baseline_policy": "l1",
            "candidate_policy": "cand.x",
            "seed_start": 7000,
            "seed_end": 7199,
            "sample_size": 200,
            "baseline_run_id": "a",
            "candidate_run_id": "b",
            "baseline_manifest_sha256": "a" * 64,
            "candidate_manifest_sha256": "b" * 64,
            "notes": "n",
            "decision_mode": "human_review",
        }
        with self.assertRaises(Exception):
            PromotionEvidence.model_validate(payload)
