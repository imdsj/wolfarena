"""Tests for the post-game review loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase
from uuid import uuid4

from backend.ai_provider import DeepSeekSettings
from backend.review import card_from_review, review_run, rule_fallback_card
from backend.strategy_library import StrategyError, StrategyLibrary


class ReviewTests(TestCase):
    def setUp(self) -> None:
        self.base = Path("training_runs") / f"test-review-{uuid4().hex}"
        self.base.mkdir(parents=True, exist_ok=True)
        self.root = self.base / "strategy"
        self.root.mkdir(parents=True, exist_ok=True)

    def _write_run(self, games: list[dict]) -> Path:
        run = self.base / "run"
        run.mkdir(parents=True, exist_ok=True)
        (run / "games.jsonl").write_text(
            "\n".join(json.dumps(game) for game in games) + "\n",
            encoding="utf-8",
        )
        (run / "actions.jsonl").write_text("", encoding="utf-8")
        return run

    def test_rule_fallback_card_is_role_aware(self) -> None:
        wolf = rule_fallback_card({"winner": "wolf"})
        good = rule_fallback_card({"winner": "good"})
        self.assertEqual(wolf["role"], "werewolf")
        self.assertEqual(good["role"], "villager")

    def test_card_from_review_without_key_is_a_valid_candidate(self) -> None:
        card = card_from_review(
            game={"winner": "wolf", "seed": 1},
            actions=[],
            settings=DeepSeekSettings(api_key=None),
        )
        self.assertEqual(card.status, "candidate")
        self.assertIsNone(card.win_rate)
        self.assertEqual(card.evidence_level, "untested")
        self.assertTrue(card.strategy_id.startswith("cand.review."))

    def test_review_run_writes_candidates_and_is_idempotent(self) -> None:
        run = self._write_run(
            [
                {"seed": 1, "status": "completed", "winner": "wolf"},
                {"seed": 2, "status": "completed", "winner": "good"},
                {"seed": 3, "status": "error", "winner": None},
            ]
        )
        written = review_run(run, strategy_root=self.root)
        self.assertEqual(len(written), 2)

        library = StrategyLibrary(self.root)
        candidates = library.load("candidate")
        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            {card.strategy_id for card in candidates},
            {path.stem for path in written},
        )
        # candidates never enter the default search set
        matches = library.search("", limit=20)
        self.assertEqual(matches, [])

        # Re-reviewing the same run must not duplicate or crash the night loop.
        self.assertEqual(review_run(run, strategy_root=self.root), [])
        self.assertEqual(len(library.load("candidate")), 2)
