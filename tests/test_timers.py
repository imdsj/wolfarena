"""Deterministic tests for server-authoritative room deadlines."""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.game_engine import (
    DayResult,
    EventType,
    NightResult,
    Phase,
    Role,
    begin_day,
    self_destruct,
)
from backend.rooms import InMemoryRoomRepository, ViewerAccess
from backend.schemas import ActionRequest
from backend.timers import RoomTimerService


class FakeRealtime:
    def __init__(self) -> None:
        self.mutations = []

    async def broadcast_mutation(self, mutation) -> None:
        self.mutations.append(mutation)


def create_room(repository: InMemoryRoomRepository):
    created = repository.create_room(
        seed=1,
        human_count=1,
        max_humans=3,
        nickname="订书机",
    )
    return created, repository.authenticate_player(
        created.room_id,
        created.player_token,
    )


class RoomTimerTests(IsolatedAsyncioTestCase):
    async def test_public_speech_timeout_advances_once(self) -> None:
        repository = InMemoryRoomRepository()
        created, _session = create_room(repository)
        room = repository._rooms[created.room_id]
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.DAY_DISCUSSION
            room.state.day_result = DayResult(
                speech_order=["p1"],
                next_speaker_index=0,
                speech_deadline=130.0,
            )
        deadline = room.state.day_result.speech_deadline
        self.assertIsNotNone(deadline)
        events_before = len(room.state.events)
        realtime = FakeRealtime()
        timer = RoomTimerService(
            repository,
            realtime,
            clock=lambda: deadline,
        )

        before = await timer.tick(now=deadline - 0.01)
        self.assertEqual(before, ())
        self.assertEqual(len(room.state.events), events_before)

        due = await timer.tick(now=deadline)
        self.assertTrue(due)
        self.assertEqual(len(realtime.mutations), len(due))
        timeout_events = [
            event
            for event in room.state.events
            if event.event_type is EventType.PUBLIC_SPEECH_TIMEOUT
        ]
        self.assertEqual(len(timeout_events), 1)

        events_after = len(room.state.events)
        repeat = await timer.tick(now=deadline)
        self.assertEqual(repeat, ())
        self.assertEqual(len(room.state.events), events_after)

    async def test_last_words_timeout_advances_once(self) -> None:
        repository = InMemoryRoomRepository()
        created, _session = create_room(repository)
        room = repository._rooms[created.room_id]
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.DAY_ANNOUNCEMENT
            room.state.night_result = NightResult(death_ids=["p1"])
            room.state.players[0].is_alive = False
            begin_day(room.state, now=100.0)
        deadline = room.state.day_result.last_words_deadline
        self.assertIsNotNone(deadline)
        realtime = FakeRealtime()
        timer = RoomTimerService(
            repository,
            realtime,
            clock=lambda: deadline,
        )

        await timer.tick(now=deadline)
        timeout_events = [
            event
            for event in room.state.events
            if event.event_type is EventType.LAST_WORDS_TIMEOUT
        ]
        self.assertEqual(len(timeout_events), 1)

        events_after = len(room.state.events)
        await timer.tick(now=deadline)
        self.assertEqual(len(room.state.events), events_after)

    async def test_idle_human_night_role_reaches_end_via_autoplay(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=3,
            human_count=1,
            max_humans=3,
            nickname="H",
        )
        room = repository._rooms[created.room_id]
        access = ViewerAccess(
            room_id=created.room_id,
            kind="player",
            player_id="p1",
        )
        repository.execute_action_and_advance_ai(
            access,
            ActionRequest(action="start_night"),
            now=0.0,
        )
        self.assertEqual(room.state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        self.assertEqual(room.state.phase_deadline_kind, "human_action")

        realtime = FakeRealtime()
        timer = RoomTimerService(repository, realtime)
        now = 0.0
        for _ in range(600):
            now += 21.0
            await timer.tick(now=now)
            if room.state.phase is Phase.END:
                break

        self.assertIs(room.state.phase, Phase.END)


class TimerLifecycleTests(IsolatedAsyncioTestCase):
    async def test_app_lifespan_starts_and_stops_timer(self) -> None:
        repository = InMemoryRoomRepository()
        application = create_app(repository)
        client = TestClient(application)

        with client:
            self.assertTrue(application.state.timer_service.running)

        self.assertFalse(application.state.timer_service.running)

    async def test_self_destruct_timeout_closes_once(self) -> None:
        repository = InMemoryRoomRepository()
        created, _session = create_room(repository)
        room = repository._rooms[created.room_id]
        wolf = next(
            player
            for player in room.state.players
            if player.role is Role.WEREWOLF
        )
        with room.lock:
            room.state.day = 4
            room.state.phase = Phase.DAY_DISCUSSION
            room.state.day_result = DayResult(
                speech_order=[
                    player.player_id
                    for player in room.state.players
                    if player.is_alive
                ]
            )
            self_destruct(room.state, wolf.player_id, now=100.0)
        deadline = room.state.day_result.self_destruct_deadline
        self.assertIsNotNone(deadline)
        self.assertIs(room.state.phase, Phase.SELF_DESTRUCT)
        realtime = FakeRealtime()
        timer = RoomTimerService(
            repository,
            realtime,
            clock=lambda: deadline,
        )

        await timer.tick(now=deadline)
        self.assertIsNot(room.state.phase, Phase.SELF_DESTRUCT)
        events_after = len(room.state.events)
        await timer.tick(now=deadline)
        self.assertEqual(len(room.state.events), events_after)
