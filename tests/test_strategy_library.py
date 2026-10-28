"""Tests for the local strategy library security boundary."""

from __future__ import annotations

from pathlib import Path
import unittest
from uuid import uuid4

from backend.strategy_library import (
    PromotionEvidence,
    StrategyCard,
    StrategyError,
    StrategyLibrary,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def candidate_card(strategy_id: str = "candidate.test-seer") -> StrategyCard:
    return StrategyCard(
        strategy_id=strategy_id,
        title="测试候选策略",
        role="seer",
        phase="NIGHT_SEER_CHECK",
        action="seer_check",
        trigger="存在未查验的存活目标",
        recommendation="优先选择未查验目标",
        rationale="避免重复查验",
        tags=["预言家", "查验", "未查验"],
        source_type="agent_observation",
        source="对局复盘候选，未经胜率验证",
        status="candidate",
        created_by="ai",
        created_at="2026-10-27T00:00:00+08:00",
    )


def promotion_evidence(reviewer: str = "订书机") -> PromotionEvidence:
    return PromotionEvidence(
        reviewer=reviewer,
        approved=True,
        baseline_policy="l0",
        candidate_policy="candidate.test-seer",
        seed_start=1000,
        seed_end=1199,
        sample_size=200,
        baseline_run_id="l0-1000-1199",
        candidate_run_id="candidate-1000-1199",
        baseline_manifest_sha256="a" * 64,
        candidate_manifest_sha256="b" * 64,
        notes="固定 seed 200 局对照通过，人工复核",
    )


class StrategyLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.test_root = (
            PROJECT_ROOT
            / "training_runs"
            / f"test-strategy-library-{uuid4().hex}"
        )
        self.library = StrategyLibrary(self.test_root)

    def test_seed_library_is_default_searchable(self) -> None:
        repository_library = StrategyLibrary(
            PROJECT_ROOT / "strategy_library"
        )

        matches = repository_library.search(
            "预言家 神职",
            role="werewolf",
            phase="NIGHT_WOLF_KILL",
        )

        self.assertTrue(matches)
        self.assertIn(
            "wolf.kill-claimed-seer",
            {match.card.strategy_id for match in matches},
        )
        self.assertTrue(
            all(match.card.status in {"seed", "validated"} for match in matches)
        )

    def test_repository_has_at_least_thirty_unique_seed_strategies(self) -> None:
        repository_library = StrategyLibrary(
            PROJECT_ROOT / "strategy_library"
        )
        seeds = repository_library.load("seed")

        self.assertGreaterEqual(len(seeds), 30)
        self.assertEqual(
            len({card.strategy_id for card in seeds}),
            len(seeds),
        )

    def test_candidate_is_not_searchable_by_default(self) -> None:
        card = candidate_card()
        self.library.record_candidate(card)

        default_matches = self.library.search(
            "预言家 查验",
            role="seer",
            phase="NIGHT_SEER_CHECK",
        )
        candidate_matches = self.library.search(
            "预言家 查验",
            role="seer",
            phase="NIGHT_SEER_CHECK",
            include_candidates=True,
        )

        self.assertEqual(default_matches, [])
        self.assertEqual(
            [match.card.strategy_id for match in candidate_matches],
            [card.strategy_id],
        )

    def test_duplicate_id_cannot_override_seed(self) -> None:
        seed_source = (
            PROJECT_ROOT
            / "strategy_library"
            / "seeds"
            / "wolf-kill-claimed-seer.json"
        )
        (self.test_root / "seeds" / seed_source.name).write_text(
            seed_source.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        duplicate = candidate_card("wolf.kill-claimed-seer")
        duplicate = duplicate.model_copy(
            update={
                "role": "werewolf",
                "phase": "NIGHT_WOLF_KILL",
                "action": "wolf_kill",
            }
        )

        with self.assertRaises(StrategyError):
            self.library.record_candidate(duplicate)

    def test_candidate_cannot_carry_unverified_win_rate(self) -> None:
        card = candidate_card()
        card = card.model_copy(update={"samples": 10, "win_rate": 0.8})
        with self.assertRaises(StrategyError):
            self.library.record_candidate(card)

    def test_candidate_requires_200_game_human_approved_evidence(self) -> None:
        self.library.record_candidate(candidate_card())

        validated = self.library.promote_candidate(
            "candidate.test-seer",
            promotion_evidence(),
        )

        self.assertEqual(validated.status, "validated")
        self.assertEqual(len(self.library.load("candidate")), 0)
        validated_matches = self.library.search(
            "未查验",
            role="seer",
            phase="NIGHT_SEER_CHECK",
        )
        self.assertEqual(
            validated_matches[0].card.strategy_id,
            "candidate.test-seer",
        )

    def test_ai_reviewer_cannot_promote(self) -> None:
        with self.assertRaises(ValueError):
            promotion_evidence(reviewer="AI")

    def test_promotion_rejects_small_sample(self) -> None:
        with self.assertRaises(ValueError):
            PromotionEvidence(
                reviewer="订书机",
                approved=True,
                baseline_policy="l0",
                candidate_policy="candidate.test",
                seed_start=1,
                seed_end=10,
                sample_size=10,
                baseline_run_id="a",
                candidate_run_id="b",
                baseline_manifest_sha256="a" * 64,
                candidate_manifest_sha256="b" * 64,
                notes="样本不足",
            )


if __name__ == "__main__":
    unittest.main()
