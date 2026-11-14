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
from backend.actions import available_actions_for_state


class HumanIdleTimeoutTests(TestCase):
    def test_vote_waits_for_the_real_player(self) -> None:
        state = create_game(seed=301, human_count=1)
        state.phase = Phase.VOTE
        state.day_result = DayResult(votes={})
        controller = AIController(InMemoryRoomRepository())

        controller._ensure_phase_deadline(state, now=100.0)

        self.assertIsNone(state.phase_deadline_kind)
        self.assertIsNone(state.phase_deadline_at)

    def test_night_action_waits_for_the_real_player(self) -> None:
        state = create_game(seed=302, human_count=1)
        human = next(player for player in state.players if player.is_human)
        human.role = Role.WEREWOLF
        state.phase = Phase.NIGHT_WOLF_KILL
        state.wolf_captain_id = human.player_id
        controller = AIController(InMemoryRoomRepository())

        controller._ensure_phase_deadline(state, now=100.0)

        self.assertIsNone(state.phase_deadline_kind)
        self.assertIsNone(state.phase_deadline_at)


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

    def test_reelection_after_captain_death_falls_back(self) -> None:
        state, wolves = self._two_human_wolves(309)
        state.phase = Phase.VOTE
        state.day = 1
        wolves[0].is_alive = False
        state.wolf_captain_id = wolves[0].player_id

        start_night(state)

        self.assertEqual(state.wolf_captain_id, wolves[1].player_id)
        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)

    def test_single_human_wolf_does_not_see_confirm_button(self) -> None:
        state = create_game(seed=310, human_count=1)
        human = next(player for player in state.players if player.is_human)
        human.role = Role.WEREWOLF
        for player in state.players:
            if player.role is Role.WEREWOLF and player is not human:
                player.is_human = False
        actions = available_actions_for_state(
            state,
            human,
            host_player_id=human.player_id,
        )
        self.assertNotIn(
            "confirm_captain",
            {action.action for action in actions},
        )
        start_night(state)
        self.assertEqual(state.wolf_captain_id, human.player_id)

    def test_two_human_wolves_race_and_repeat_confirm_is_idempotent(self) -> None:
        state, wolves = self._two_human_wolves(311)
        first_actions = available_actions_for_state(
            state,
            wolves[0],
            host_player_id=wolves[0].player_id,
        )
        self.assertIn(
            "confirm_captain",
            {action.action for action in first_actions},
        )
        elect_wolf_captain(state, captain_id=wolves[1].player_id)
        elect_wolf_captain(state, captain_id=wolves[1].player_id)
        self.assertEqual(state.wolf_captain_id, wolves[1].player_id)
        second_actions = available_actions_for_state(
            state,
            wolves[0],
            host_player_id=wolves[0].player_id,
        )
        self.assertNotIn(
            "confirm_captain",
            {action.action for action in second_actions},
        )
        with self.assertRaisesRegex(ValueError, "抢先确认"):
            elect_wolf_captain(state, captain_id=wolves[0].player_id)


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
