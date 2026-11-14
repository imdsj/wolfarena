"""Tests for structure-aware tactic retrieval."""

from __future__ import annotations

from unittest import TestCase

from backend.game_engine import (
    EventType,
    Phase,
    Role,
    Visibility,
    append_event,
    create_game,
)
from backend.rag_eval import run_ablation
from backend.tactic_retrieval import build_context, rank_tactics


class StructuredRetrievalTests(TestCase):
    def test_hard_rule_scene_hits_hard_rule_tactic(self) -> None:
        state = create_game(seed=9100, human_count=0)
        state.phase = Phase.DAY_DISCUSSION
        state.day = 1
        speaker = state.players[4]  # seat 5
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            visibility=Visibility.PUBLIC,
            data={"content": "我是预言家，昨晚验4号金水、2号查杀。"},
        )
        actor = next(
            player
            for player in state.players
            if player.role is Role.VILLAGER
        )
        ids = [
            match.card.strategy_id
            for match in rank_tactics(state, actor, limit=3)
        ]
        self.assertIn("good.hard-rule-first", ids)

    def test_silent_seer_scene_prefers_cautious_tactic(self) -> None:
        state = create_game(seed=9101, human_count=0)
        state.phase = Phase.NIGHT_SEER_CHECK
        actor = next(
            player for player in state.players if player.role is Role.SEER
        )
        ids = [
            match.card.strategy_id
            for match in rank_tactics(state, actor, limit=3)
        ]
        self.assertIn("seer.check-unverified", ids)

    def test_results_always_match_role(self) -> None:
        state = create_game(seed=9102, human_count=0)
        state.phase = Phase.VOTE
        actor = next(
            player for player in state.players if player.role is Role.WEREWOLF
        )
        for match in rank_tactics(state, actor, limit=3):
            self.assertEqual(match.card.role, "werewolf")

    def test_context_collects_seer_claim_signals(self) -> None:
        state = create_game(seed=9103, human_count=0)
        state.phase = Phase.NIGHT_WOLF_KILL
        speaker = state.players[3]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            visibility=Visibility.PUBLIC,
            data={"content": "我是预言家，6号查杀。"},
        )
        actor = next(
            player for player in state.players if player.role is Role.WEREWOLF
        )
        context = build_context(state, actor)
        self.assertIn("预言家", context.signals)
        self.assertIn("自报", context.signals)

    def test_limit_must_be_positive(self) -> None:
        state = create_game(seed=9104, human_count=0)
        state.phase = Phase.VOTE
        actor = state.players[0]
        with self.assertRaises(ValueError):
            rank_tactics(state, actor, limit=0)


class AblationTests(TestCase):
    def test_structured_beats_keyword_retrieval(self) -> None:
        result = run_ablation()
        self.assertEqual(result["scenario_count"], 12)
        mean = result["mean_recall"]
        self.assertGreater(
            mean["structured_rag"],
            mean["keyword_rag"],
        )
        self.assertGreaterEqual(mean["structured_rag"], 0.9)


if __name__ == "__main__":
    import unittest

    unittest.main()
