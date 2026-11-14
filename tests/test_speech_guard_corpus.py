"""Corpus-driven tests for the generated-speech safety guards.

The fixture is the single source of truth: changing a prompt or a guard must
not silently loosen the expectations recorded here.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import TestCase

from backend.logic_audit import (
    asserts_unspoken_identity,
    contradicts_own_report,
    dead_vote_targets,
    impossible_seer_claim_in_text,
    mentions_two_nights_on_day_one,
    speech_claims_living_dead,
    wolf_speech_targets_dead,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "speech_cases.json"
)


class SpeechGuardCorpusTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        cls.cases = payload["cases"]

    def test_corpus_has_positive_and_negative_cases(self) -> None:
        flags = [case.get("expect", {}) for case in self.cases]
        keys = {
            "asserts_unspoken_identity",
            "speech_claims_living_dead",
            "contradicts_own_report",
            "dead_vote_targets",
            "wolf_speech_targets_dead",
            "impossible_seer_claim_in_text",
            "mentions_two_nights_on_day_one",
        }
        for key in keys:
            values = {flag.get(key) for flag in flags}
            self.assertIn(True, values, f"{key} 缺少正例")
            self.assertIn(False, values, f"{key} 缺少反例")

    def test_every_case_matches_expectation(self) -> None:
        for case in self.cases:
            with self.subTest(name=case["name"]):
                expect = case["expect"]
                text = case["text"]
                day = int(case["day"])
                unspoken = set(case.get("unspoken_seats", []))
                alive = set(case.get("alive_seats", []))
                dead = set(case.get("dead_seats", []))
                speaker = int(case.get("speaker_seat", 9))

                self.assertEqual(
                    asserts_unspoken_identity(text, unspoken, speaker),
                    expect["asserts_unspoken_identity"],
                )
                self.assertEqual(
                    speech_claims_living_dead(text, alive),
                    expect["speech_claims_living_dead"],
                )
                self.assertEqual(
                    contradicts_own_report(text),
                    expect["contradicts_own_report"],
                )
                self.assertEqual(
                    bool(dead_vote_targets(text, dead)),
                    expect["dead_vote_targets"],
                )
                self.assertEqual(
                    wolf_speech_targets_dead(text, dead),
                    expect["wolf_speech_targets_dead"],
                )
                self.assertEqual(
                    impossible_seer_claim_in_text(text, day),
                    expect["impossible_seer_claim_in_text"],
                )
                self.assertEqual(
                    mentions_two_nights_on_day_one(text, day),
                    expect["mentions_two_nights_on_day_one"],
                )


if __name__ == "__main__":
    import unittest

    unittest.main()
