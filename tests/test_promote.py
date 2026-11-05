"""Tests for candidate evaluation and the promotion evidence harness."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from uuid import uuid4

from backend.ai_provider import DeepSeekSettings
from backend.promote import TacticPolicy, evaluate_candidate
from backend.strategy_library import StrategyCard, StrategyLibrary


def candidate_card(strategy_id: str = "cand.test-tactic") -> StrategyCard:
    return StrategyCard(
        schema_version=1,
        strategy_id=strategy_id,
        title="好人集中归票",
        role="villager",
        phase="VOTE",
        action="vote",
        trigger="白天投票阶段。",
        recommendation="集中票数到最可疑目标。",
        rationale="避免分票。",
        risk="误判会误伤好人。",
        evidence_level="untested",
        source_type="agent_observation",
        source="测试",
        status="candidate",
        created_by="ai",
        created_at="2026-11-05T00:00:00+08:00",
    )


class TacticPolicyTests(TestCase):
    def test_without_key_falls_back_to_l1_target(self) -> None:
        policy = TacticPolicy(
            seed=1,
            card=candidate_card(),
            settings=DeepSeekSettings(api_key=None),
        )
        from backend.game_engine import create_game

        state = create_game(seed=1, human_count=0)
        actor = state.players[0]
        view = SimpleNamespace(
            action="vote",
            target_ids=["p2", "p3"],
            choices=[],
        )
        picked = policy.choose_target(state, actor, view)
        self.assertIn(picked, view.target_ids)


class EvaluateCandidateTests(TestCase):
    def setUp(self) -> None:
        self.base = Path("training_runs") / f"test-promote-{uuid4().hex}"
        self.base.mkdir(parents=True, exist_ok=True)
        self.root = self.base / "strategy"
        self.root.mkdir(parents=True, exist_ok=True)
        library = StrategyLibrary(self.root)
        library.record_candidate(candidate_card())

    def test_evaluate_writes_evidence_and_delta(self) -> None:
        out = self.base / "evidence"
        result = evaluate_candidate(
            "cand.test-tactic",
            strategy_root=self.root,
            seed_start=1000,
            games=4,
            settings=DeepSeekSettings(api_key=None),
            out_dir=out,
        )
        self.assertEqual(result["sample_size"], 4)
        self.assertIn("delta_good_win_rate", result)
        self.assertEqual(len(result["confidence_interval_95"]), 2)

        evidence = json.loads(
            (out / "promotion_evidence.json").read_text(encoding="utf-8")
        )
        self.assertFalse(evidence["approved"])
        self.assertEqual(len(evidence["baseline_manifest_sha256"]), 64)
        self.assertEqual(len(evidence["candidate_manifest_sha256"]), 64)
        self.assertEqual(evidence["sample_size"], 4)

    def test_missing_candidate_raises(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_candidate(
                "cand.not-there",
                strategy_root=self.root,
                seed_start=1000,
                games=2,
                settings=DeepSeekSettings(api_key=None),
            )
