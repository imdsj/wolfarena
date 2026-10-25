"""Witch knife-target visibility through the room snapshot boundary."""

from __future__ import annotations

from unittest import TestCase

from backend.game_engine import NightResult, Phase, Role, get_player
from backend.rooms import InMemoryRoomRepository


class WitchSnapshotVisibilityTests(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRoomRepository()
        self.created = self.repository.create_room(
            seed=28,
            human_count=1,
            max_humans=3,
            nickname="女巫测试",
        )
        self.session = self.repository.authenticate_player(
            self.created.room_id,
            self.created.player_token,
        )
        self.room = self.repository._rooms[self.created.room_id]
        self.witch = get_player(self.room.state, "p1")
        self.assertEqual(self.witch.role, Role.WITCH)

    def prepare_night(self, wolf_target_id: str | None) -> None:
        with self.room.lock:
            self.room.state.phase = Phase.NIGHT_WITCH_ACTION
            self.room.state.night_result = NightResult(
                wolf_target_id=wolf_target_id,
            )

    def snapshot(self):
        return self.repository.snapshot_for_access(
            self.room,
            self.session.access,
            now=100.0,
        )

    def test_witch_with_antidote_sees_exact_wolf_target(self) -> None:
        self.prepare_night("p2")

        snapshot = self.snapshot()

        self.assertTrue(snapshot.witch_kill_target_visible)
        self.assertEqual(snapshot.witch_kill_target_id, "p2")

    def test_witch_with_antidote_can_distinguish_empty_kill(self) -> None:
        self.prepare_night(None)

        snapshot = self.snapshot()

        self.assertTrue(snapshot.witch_kill_target_visible)
        self.assertIsNone(snapshot.witch_kill_target_id)

    def test_witch_without_antidote_cannot_see_target(self) -> None:
        self.prepare_night("p2")
        with self.room.lock:
            self.room.state.antidote_available = False

        snapshot = self.snapshot()

        self.assertFalse(snapshot.witch_kill_target_visible)
        self.assertIsNone(snapshot.witch_kill_target_id)

    def test_non_witch_never_receives_witch_target(self) -> None:
        second_repository = InMemoryRoomRepository()
        created = second_repository.create_room(
            seed=1,
            human_count=1,
            max_humans=3,
            nickname="非女巫测试",
        )
        session = second_repository.authenticate_player(
            created.room_id,
            created.player_token,
        )
        room = second_repository._rooms[created.room_id]
        player = get_player(room.state, "p1")
        self.assertNotEqual(player.role, Role.WITCH)
        with room.lock:
            room.state.phase = Phase.NIGHT_WITCH_ACTION
            room.state.night_result = NightResult(wolf_target_id="p2")

        snapshot = second_repository.snapshot_for_access(
            room,
            session.access,
            now=100.0,
        )

        self.assertFalse(snapshot.witch_kill_target_visible)
        self.assertIsNone(snapshot.witch_kill_target_id)


if __name__ == "__main__":
    import unittest

    unittest.main()
