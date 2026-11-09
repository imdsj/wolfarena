"""Regression tests for 2-3 human multiplayer flow fixes."""

from __future__ import annotations

from unittest import TestCase

from backend.ai_controller import AIController
from backend.game_engine import (
    DayResult,
    EventType,
    Phase,
    Role,
    create_game,
    elect_wolf_captain,
    start_night,
)
from backend.rooms import InMemoryRoomRepository
from backend.schemas import ActionRequest


class HumanIdleTimeoutTests(TestCase):
    def test_vote_arms_a_ten_second_human_deadline(self) -> None:
        state = create_game(seed=301, human_count=1)
        state.phase = Phase.VOTE
        state.day_result = DayResult(votes={})
        controller = AIController(InMemoryRoomRepository())

        controller._ensure_phase_deadline(state, now=100.0)

        self.assertEqual(state.phase_deadline_kind, "human_action")
        self.assertEqual(state.phase_deadline_at, 110.0)

    def test_night_action_arms_a_thirty_second_human_deadline(self) -> None:
        state = create_game(seed=302, human_count=1)
        human = next(player for player in state.players if player.is_human)
        human.role = Role.WEREWOLF
        state.phase = Phase.NIGHT_WOLF_KILL
        state.wolf_captain_id = human.player_id
        controller = AIController(InMemoryRoomRepository())

        controller._ensure_phase_deadline(state, now=100.0)

        self.assertEqual(state.phase_deadline_kind, "human_action")
        self.assertEqual(state.phase_deadline_at, 130.0)

    def test_idle_human_vote_is_auto_abstained(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=303,
            human_count=1,
            max_humans=3,
            nickname="房主",
        )
        room = repository._rooms[created.room_id]
        human = next(player for player in room.state.players if player.is_human)
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.VOTE
            room.state.day_result = DayResult(votes={})
            room.state.phase_deadline_at = 99.0
            room.state.phase_deadline_kind = "human_action"

        repository.process_expired_deadlines(now=100.0)

        human_vote = next(
            event
            for event in room.state.events
            if event.event_type is EventType.VOTE_CAST
            and event.actor_id == human.player_id
        )
        self.assertTrue(human_vote.data["abstain"])


class CaptainConfirmationTests(TestCase):
    def _two_human_wolves(self, seed: int):
        state = create_game(seed=seed, human_count=0)
        wolves = [
            player
            for player in state.players
            if player.role is Role.WEREWOLF
        ]
        wolves[0].is_human = True
        wolves[1].is_human = True
        return state, wolves

    def test_first_confirmation_wins(self) -> None:
        state, wolves = self._two_human_wolves(304)

        elect_wolf_captain(state, captain_id=wolves[1].player_id)

        self.assertEqual(state.wolf_captain_id, wolves[1].player_id)

    def test_second_confirmation_is_rejected(self) -> None:
        state, wolves = self._two_human_wolves(305)
        elect_wolf_captain(state, captain_id=wolves[1].player_id)

        with self.assertRaises(ValueError):
            elect_wolf_captain(state, captain_id=wolves[0].player_id)

    def test_start_night_blocks_until_captain_confirmed(self) -> None:
        state, _wolves = self._two_human_wolves(306)

        with self.assertRaises(ValueError):
            start_night(state)


class ReservedSeatGateTests(TestCase):
    def test_start_is_blocked_until_reserved_humans_join(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=307,
            human_count=2,
            max_humans=3,
            nickname="房主",
        )
        session = repository.authenticate_player(
            created.room_id,
            created.player_token,
        )
        room = repository._rooms[created.room_id]
        with room.lock:
            # Make sure neither reserved seat is a wolf, so starting the night
            # is not blocked by the human-wolf captain gate in this test.
            room.state.players[0].role = Role.VILLAGER
            room.state.players[1].role = Role.VILLAGER

        with self.assertRaises(ValueError):
            repository.execute_action(
                session.access,
                ActionRequest(action="start_night"),
                now=100.0,
            )

        repository.join_room(created.room_id, "二号", seat=2)
        mutation = repository.execute_action(
            session.access,
            ActionRequest(action="start_night"),
            now=100.0,
        )
        self.assertNotEqual(mutation.room.state.phase, Phase.INIT)


class PerPlayerContinueTests(TestCase):
    def test_continue_waits_for_every_living_human(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=308,
            human_count=1,
            max_humans=3,
            nickname="房主",
        )
        host = repository.authenticate_player(
            created.room_id,
            created.player_token,
        )
        joined, _mutation = repository.join_room(
            created.room_id,
            "二号",
            seat=2,
        )
        second = repository.authenticate_player(
            created.room_id,
            joined.player_token,
        )
        room = repository._rooms[created.room_id]
        with room.lock:
            room.continue_gate = True
            room.continue_acks.clear()

        repository.request_continue(created.room_id, host.access, now=100.0)
        self.assertTrue(room.continue_gate)

        repository.request_continue(created.room_id, second.access, now=100.0)
        self.assertFalse(room.continue_gate)
