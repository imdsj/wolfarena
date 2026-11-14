"""Tests for the HTTP-facing strategy laboratory."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from backend.strategy_admin import (
    list_library,
    reject,
    reviewer_authorized,
    rollback,
    submit_candidate,
)
from backend.strategy_library import StrategyCard, StrategyLibrary


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ReviewerAuthTests(TestCase):
    def test_requires_both_sides(self) -> None:
        self.assertFalse(reviewer_authorized(None, "secret"))
        self.assertFalse(reviewer_authorized("secret", None))
        self.assertFalse(reviewer_authorized("", "secret"))

    def test_constant_time_comparison(self) -> None:
        self.assertTrue(reviewer_authorized("secret", "secret"))
        self.assertFalse(reviewer_authorized("wrong", "secret"))


class StrategyAdminTests(TestCase):
    def setUp(self) -> None:
        self.root = (
            PROJECT_ROOT
            / "training_runs"
            / f"test-strategy-admin-{uuid4().hex}"
        )
        self.library = StrategyLibrary(self.root)

    def _payload(self, **overrides):
        payload = {
            "title": "测试用户战术",
            "role": "villager",
            "phase": "VOTE",
            "action": "vote",
            "trigger": "白天投票阶段",
            "recommendation": "跟最高嫌疑归票",
            "rationale": "减少分票",
            "risk": "可能被狼队带节奏",
            "directive": "vote_most_accused",
            "created_by": "测试员",
        }
        payload.update(overrides)
        return payload

    def test_submit_lands_in_candidates(self) -> None:
        card = submit_candidate(self._payload(), strategy_root=self.root)
        self.assertEqual(card["status"], "candidate")
        self.assertTrue(card["strategy_id"].startswith("cand.user."))
        self.assertEqual(len(self.library.load("candidate")), 1)

    def test_unknown_directive_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            submit_candidate(
                self._payload(directive="not_a_real_directive"),
                strategy_root=self.root,
            )

    def test_list_library_groups_by_status(self) -> None:
        submit_candidate(self._payload(), strategy_root=self.root)
        view = list_library(strategy_root=self.root)
        self.assertEqual(view["counts"]["candidate"], 1)
        self.assertEqual(len(view["candidates"]), 1)
        self.assertIn("validated", view)
        self.assertIn("rejected", view)

    def test_reject_moves_to_rejected(self) -> None:
        card = submit_candidate(self._payload(), strategy_root=self.root)
        reject(card["strategy_id"], "证据不足", strategy_root=self.root)
        self.assertEqual(len(self.library.load("candidate")), 0)
        self.assertEqual(len(self.library.load("rejected")), 1)

    def test_rollback_demotes_validated(self) -> None:
        card = StrategyCard(
            strategy_id="cand.user.rollback-test",
            title="回滚测试",
            role="villager",
            phase="VOTE",
            action="vote",
            trigger="t",
            recommendation="r",
            rationale="r2",
            risk="risk text",
            source_type="team",
            source="test",
            status="validated",
            created_by="t",
            created_at="2026-01-01T00:00:00+00:00",
        )
        (self.root / "validated" / "cand.user.rollback-test.json").write_text(
            card.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        result = rollback(
            "cand.user.rollback-test",
            "测试回滚",
            strategy_root=self.root,
        )
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(len(self.library.load("validated")), 0)
        self.assertEqual(len(self.library.load("candidate")), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
