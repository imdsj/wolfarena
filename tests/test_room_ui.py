"""UI-facing regressions: night banner, hidden system actions, dead last words."""

from __future__ import annotations

from unittest import TestCase

from backend.game_engine import DayResult, Phase, create_game
from backend.rooms import InMemoryRoomRepository, ViewerAccess
from backend.speech_composer import dead_notice


class NightSummaryTests(TestCase):
    def _state(self, phase: Phase):
        state = create_game(seed=3, human_count=0)
        state.day = 2
        state.phase = phase
        return state

    def test_peaceful_night_is_named(self) -> None:
        state = self._state(Phase.DAY_DISCUSSION)
        state.day_result = DayResult(announced_death_ids=[])
        summary = InMemoryRoomRepository._last_night_summary(state)
        self.assertIsNotNone(summary)
        self.assertIn("平安夜", summary)

    def test_dead_seats_are_listed(self) -> None:
        state = self._state(Phase.DAY_ANNOUNCEMENT)
        victim = state.players[2]
        state.day_result = DayResult(announced_death_ids=[victim.player_id])
        summary = InMemoryRoomRepository._last_night_summary(state)
        self.assertIsNotNone(summary)
        self.assertIn(f"{victim.seat} 号", summary)

    def test_night_phases_hide_the_banner(self) -> None:
        state = self._state(Phase.NIGHT_WOLF_KILL)
        state.day_result = DayResult(announced_death_ids=[])
        self.assertIsNone(
            InMemoryRoomRepository._last_night_summary(state)
        )


class SystemActionVisibilityTests(TestCase):
    def test_host_is_not_offered_manual_phase_buttons(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=1,
            human_count=1,
            max_humans=3,
            nickname="订书机",
        )
        access = ViewerAccess(
            room_id=created.room_id,
            kind="player",
            player_id="p1",
        )
        room = repository._rooms[created.room_id]
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.DAY_ANNOUNCEMENT
            room.state.day_result = DayResult(announced_death_ids=[])
        snapshot = repository.snapshot_for_access(room, access)
        offered = {action.action for action in snapshot.available_actions}
        self.assertNotIn("begin_day", offered)
        self.assertNotIn("resolve_night", offered)
        self.assertNotIn("resolve_vote", offered)
        self.assertIsNotNone(snapshot.last_night_summary)


class DeadLastWordsTests(TestCase):
    def test_last_words_say_the_speaker_is_out(self) -> None:
        state = create_game(seed=5, human_count=0)
        actor = state.players[0]
        state.day_result = DayResult(
            death_causes={actor.player_id: ["hunter_shot"]}
        )
        text = dead_notice(state, actor)
        self.assertIn("已经出局", text)
        self.assertIn("猎人", text)
        self.assertIn("遗言", text)
