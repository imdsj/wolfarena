"""Tests for the screenshot review transcript auditor."""

from __future__ import annotations

from unittest import TestCase

from backend.vision_review import review_transcript


class VisionReviewTests(TestCase):
    def test_flags_one_night_two_checks(self) -> None:
        result = review_transcript(
            ["6号：我是预言家，昨晚验4号金水、2号查杀。"],
            day=1,
        )
        kinds = {finding["kind"] for finding in result["findings"]}
        self.assertIn("impossible_seer_checks", kinds)

    def test_flags_gold_water_banish(self) -> None:
        result = review_transcript(
            ["3号：1号是金水，今天票1号。"],
            day=2,
        )
        kinds = {finding["kind"] for finding in result["findings"]}
        self.assertIn("report_vs_vote", kinds)

    def test_flags_role_flip_across_lines(self) -> None:
        result = review_transcript(
            ["5号：我是女巫。", "5号：我是猎人。"],
            day=2,
        )
        kinds = {finding["kind"] for finding in result["findings"]}
        self.assertIn("role_flip", kinds)

    def test_aggregates_accusations(self) -> None:
        result = review_transcript(
            ["1号：票6号。", "2号：6号是狼。"],
            day=1,
        )
        accused = {entry["seat"] for entry in result["top_accused"]}
        self.assertIn(6, accused)

    def test_empty_transcript_is_clean(self) -> None:
        result = review_transcript([], day=1)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["top_accused"], [])


if __name__ == "__main__":
    import unittest

    unittest.main()
