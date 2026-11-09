"""Tests for public vote-history analysis."""

from __future__ import annotations

from unittest import TestCase

from backend.game_engine import (
    EventType,
    Visibility,
    append_event,
    create_game,
)
from backend.vote_analysis import (
    consensus_defectors,
    format_vote_analysis,
    same_vote_blocks,
    vote_history,
)


class VoteAnalysisTests(TestCase):
    def _state_with_two_days(self):
        state = create_game(seed=330, human_count=0)
        state.day = 1
        append_event(
            state,
            EventType.VOTE_RESULT,
            visibility=Visibility.PUBLIC,
            data={
                "votes": {
                    "p1": "p3",
                    "p2": "p3",
                    "p3": "p1",
                    "p4": None,
                }
            },
        )
        state.day = 2
        append_event(
            state,
            EventType.VOTE_RESULT,
            visibility=Visibility.PUBLIC,
            data={
                "votes": {
                    "p1": "p5",
                    "p2": "p5",
                    "p3": "p1",
                    "p4": "p5",
                }
            },
        )
        return state

    def test_history_is_mapped_to_seats(self) -> None:
        state = self._state_with_two_days()
        history = vote_history(state, state.players[0])
        self.assertEqual(history[1][1], 3)
        self.assertEqual(history[1][4], None)
        self.assertEqual(history[2][3], 1)

    def test_consistent_pair_is_reported_as_a_block(self) -> None:
        state = self._state_with_two_days()
        history = vote_history(state, state.players[0])
        self.assertIn((1, 2, 2), same_vote_blocks(history))

    def test_defectors_skip_abstain(self) -> None:
        state = self._state_with_two_days()
        history = vote_history(state, state.players[0])
        defectors = consensus_defectors(history)
        self.assertEqual(defectors[3], 2)
        self.assertNotIn(4, defectors)

    def test_prompt_block_mentions_history_and_block(self) -> None:
        state = self._state_with_two_days()
        text = format_vote_analysis(state, state.players[0])
        self.assertIn("第1天", text)
        self.assertIn("1号与2号连续2天同票", text)
