"""Tests that the wolf counterclaim has an owner and abstention can be called."""

from __future__ import annotations

from unittest import TestCase

from backend.ai_growth import _abstain_is_called
from backend.game_engine import (
    EventType,
    Role,
    append_event,
    create_game,
)
from backend.speech_composer import _counterclaim_note


class CounterclaimOwnerTests(TestCase):
    def setUp(self) -> None:
        self.state = create_game(seed=17, human_count=0)
        self.wolves = sorted(
            (p for p in self.state.players if p.role is Role.WEREWOLF),
            key=lambda p: p.seat,
        )
        self.good_seat = next(
            p.seat for p in self.state.players if p.role is Role.VILLAGER
        )

    def _claim_seer(self, seat: int) -> None:
        player = next(p for p in self.state.players if p.seat == seat)
        append_event(
            self.state,
            EventType.PUBLIC_SPEECH,
            actor_id=player.player_id,
            data={"content": f"我是{seat}号预言家，昨晚验7号是狼人。"},
        )

    def test_lowest_wolf_must_counterclaim(self) -> None:
        self._claim_seer(self.good_seat)
        note = _counterclaim_note(self.state, self.wolves[0])
        self.assertIn("本回合强制", note)
        self.assertIn("自称预言家", note)

    def test_other_wolves_stand_down(self) -> None:
        self._claim_seer(self.good_seat)
        note = _counterclaim_note(self.state, self.wolves[-1])
        self.assertIn("本回合分工", note)
        self.assertIn(f"{self.wolves[0].seat} 号负责", note)

    def test_no_note_without_a_seer_claim(self) -> None:
        self.assertEqual(_counterclaim_note(self.state, self.wolves[0]), "")

    def test_no_note_after_a_wolf_already_claimed(self) -> None:
        self._claim_seer(self.good_seat)
        self._claim_seer(self.wolves[-1].seat)
        self.assertEqual(_counterclaim_note(self.state, self.wolves[0]), "")

    def test_villagers_never_get_the_note(self) -> None:
        self._claim_seer(self.good_seat)
        villager = next(p for p in self.state.players if p.role is Role.VILLAGER)
        self.assertEqual(_counterclaim_note(self.state, villager), "")


class AbstainCallTests(TestCase):
    def setUp(self) -> None:
        self.state = create_game(seed=23, human_count=0)
        self.actor = self.state.players[0]

    def _say(self, text: str) -> None:
        append_event(
            self.state,
            EventType.PUBLIC_SPEECH,
            actor_id=self.state.players[1].player_id,
            data={"content": text},
        )

    def test_detects_a_call_to_hold_votes(self) -> None:
        self._say("今天没把握，大家弃票，别误伤好人。")
        self.assertTrue(_abstain_is_called(self.state, self.actor))

    def test_normal_speech_is_not_a_call(self) -> None:
        self._say("我怀疑4号，先票4号。")
        self.assertFalse(_abstain_is_called(self.state, self.actor))
