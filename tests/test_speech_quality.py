"""Tests for the anti-repetition speech check."""

from __future__ import annotations

from unittest import TestCase

from backend.speech_quality import is_repetitive, similarity


class SpeechQualityTests(TestCase):
    def test_identical_speech_is_repetitive(self) -> None:
        text = "5号首夜查杀3号，我更倾向5号，等9号发言再定票。"
        self.assertTrue(is_repetitive(text, [text]))
        self.assertGreater(similarity(text, text), 0.99)

    def test_new_information_is_not_repetitive(self) -> None:
        old = "5号首夜查杀3号，我更倾向5号，等9号发言再定票。"
        new = "我今天看票型：4号和7号连续两天同票，先记这一对。"
        self.assertFalse(is_repetitive(new, [old]))

    def test_short_phrase_is_not_treated_as_copy(self) -> None:
        self.assertFalse(is_repetitive("同意", ["同意"]))
