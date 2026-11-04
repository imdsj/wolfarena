"""Tests for the narrator announcements in the room snapshot."""

from __future__ import annotations

from unittest import TestCase

from backend.game_engine import (
    DayResult,
    NightResult,
    Phase,
    Role,
    create_game,
)
from backend.rooms import InMemoryRoomRepository, ViewerAccess


class NarrationTests(TestCase):
    def test_death_and_peaceful_night_are_announced(self) -> None:
        repo = InMemoryRoomRepository()
        created = repo.create_room(
            seed=1,
            human_count=1,
            max_humans=3,
            nickname="H",
        )
        room = repo._rooms[created.room_id]
        access = ViewerAccess(
            room_id=created.room_id,
            kind="player",
            player_id="p1",
        )
        with room.lock:
            room.state.phase = Phase.DAY_ANNOUNCEMENT
            room.state.day = 1
            room.state.day_result = DayResult(announced_death_ids=["p2"])
        snapshot = repo.snapshot_for_access(room, access)
        self.assertTrue(any("被淘汰" in line for line in snapshot.announcements))

        with room.lock:
            room.state.day_result.announced_death_ids = []
        snapshot = repo.snapshot_for_access(room, access)
        self.assertTrue(any("平安夜" in line for line in snapshot.announcements))

    def test_seer_sees_own_result_but_villager_does_not(self) -> None:
        state = create_game(seed=3, human_count=0)
        seer = next(p for p in state.players if p.role is Role.SEER)
        villager = next(p for p in state.players if p.role is Role.VILLAGER)
        state.phase = Phase.DAY_DISCUSSION
        state.night_result = NightResult(
            seer_target_id="p2",
            seer_result="wolf",
        )
        seer_lines = InMemoryRoomRepository._announcements(
            state,
            ViewerAccess("r", "player", seer.player_id),
        )
        villager_lines = InMemoryRoomRepository._announcements(
            state,
            ViewerAccess("r", "player", villager.player_id),
        )
        self.assertTrue(any("查验结果" in line for line in seer_lines))
        self.assertFalse(any("查验结果" in line for line in villager_lines))
