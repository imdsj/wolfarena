"""Tests for grounding speech in what was actually said."""

from __future__ import annotations

from unittest import TestCase

from backend.speech_quality import fabricates_reference, seat_utterances


class FabricatedReferenceTests(TestCase):
    def setUp(self) -> None:
        self.lines = [
            "1 号：我是1号，今天先听听大家怎么说。",
            "3 号：我是预言家，昨晚验7号是狼人，大家跟我票7。",
        ]

    def test_invents_a_fact_for_another_seat(self) -> None:
        """The reported bug: seat 2 credits seat 1 with a quiet night."""

        self.assertTrue(
            fabricates_reference("2号说1号提到了平安夜，这话有问题。", self.lines)
        )

    def test_accepts_a_real_report(self) -> None:
        self.assertFalse(
            fabricates_reference("3号说7号是狼人，我跟他票。", self.lines)
        )

    def test_rejects_a_quote_nobody_said(self) -> None:
        self.assertTrue(
            fabricates_reference("1号说了「平安夜」，我觉得可疑。", self.lines)
        )

    def test_accepts_a_real_quote(self) -> None:
        self.assertFalse(
            fabricates_reference("3号说了「昨晚验7号是狼人」，我跟。", self.lines)
        )

    def test_plain_opinion_is_not_flagged(self) -> None:
        self.assertFalse(fabricates_reference("我怀疑4号，先记着。", self.lines))

    def test_seat_utterances_maps_each_seat(self) -> None:
        spoken = seat_utterances(self.lines)
        self.assertIn("预言家", spoken.get(3, ""))
        self.assertNotIn("预言家", spoken.get(1, ""))
