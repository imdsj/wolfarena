"""Contract tests for server-authoritative countdown fields."""

from __future__ import annotations

import unittest

from backend.game_engine import DayResult, Phase
from backend.rooms import InMemoryRoomRepository


class SnapshotTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRoomRepository()
        self.created = self.repository.create_room(
            seed=1,
            human_count=1,
            max_humans=3,
            nickname="订书机",
        )
        self.session = self.repository.authenticate_player(
            self.created.room_id,
            self.created.player_token,
        )
        self.room = self.repository._rooms[self.created.room_id]

    def snapshot(self, *, now: float):
        return self.repository.snapshot_for_access(
            self.room,
            self.session.access,
            now=now,
        )

    def test_init_snapshot_has_server_time_without_a_deadline(self) -> None:
        snapshot = self.snapshot(now=100.0)

        self.assertEqual(snapshot.server_time, 100.0)
        self.assertIsNone(snapshot.deadline_kind)
        self.assertIsNone(snapshot.deadline_at)
        self.assertIsNone(snapshot.remaining_ms)

    def test_public_speech_snapshot_publishes_exact_deadline(self) -> None:
        with self.room.lock:
            self.room.state.phase = Phase.DAY_DISCUSSION
            self.room.state.day_result = DayResult(
                speech_order=["p1"],
                speech_deadline=130.0,
            )

        snapshot = self.snapshot(now=100.25)

        self.assertEqual(snapshot.deadline_kind, "speech")
        self.assertEqual(snapshot.deadline_at, 130.0)
        self.assertEqual(snapshot.remaining_ms, 29_750)

    def test_last_words_and_self_destruct_keep_their_deadline_kind(self) -> None:
        cases = (
            ("last_words", Phase.DAY_LAST_WORDS, 111.0),
            ("self_destruct", Phase.SELF_DESTRUCT, 120.0),
        )
        for expected_kind, phase, deadline in cases:
            with self.subTest(kind=expected_kind):
                with self.room.lock:
                    self.room.state.phase = phase
                    self.room.state.day_result = DayResult(
                        last_words_deadline=(
                            deadline if phase is Phase.DAY_LAST_WORDS else None
                        ),
                        self_destruct_deadline=(
                            deadline if phase is Phase.SELF_DESTRUCT else None
                        ),
                    )

                snapshot = self.snapshot(now=100.0)

                self.assertEqual(snapshot.deadline_kind, expected_kind)
                self.assertEqual(snapshot.deadline_at, deadline)
                self.assertEqual(
                    snapshot.remaining_ms,
                    int((deadline - 100) * 1000),
                )

    def test_expired_deadline_is_clamped_for_display(self) -> None:
        with self.room.lock:
            self.room.state.phase = Phase.SELF_DESTRUCT
            self.room.state.day_result = DayResult(
                self_destruct_deadline=110.0,
            )

        snapshot = self.snapshot(now=111.0)

        self.assertEqual(snapshot.deadline_kind, "self_destruct")
        self.assertEqual(snapshot.remaining_ms, 0)


if __name__ == "__main__":
    unittest.main()
