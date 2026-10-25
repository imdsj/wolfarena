"""Deterministic AI turn-driver tests."""

from __future__ import annotations

from unittest import TestCase
from unittest.mock import patch

from backend.ai_controller import AIController
from backend.actions import available_actions_for_state
from backend.ai_growth import L0Policy
from backend.game_engine import DayResult, EventType, NightResult, Phase, Role
from backend.rooms import InMemoryRoomRepository
from backend.schemas import ActionRequest
from tests.test_game_engine import controlled_game


def create_seeded_room(repository: InMemoryRoomRepository, seed: int = 1):
    return repository.create_room(
        seed=seed,
        human_count=1,
        max_humans=3,
        nickname="订书机",
    )


def start_with_ai(repository: InMemoryRoomRepository, seed: int = 1):
    created = create_seeded_room(repository, seed)
    session = repository.authenticate_player(
        created.room_id,
        created.player_token,
    )
    mutation = repository.execute_action_and_advance_ai(
        session.access,
        ActionRequest(action="start_night"),
        now=100.0,
    )
    return created, session, mutation


class AIControllerTests(TestCase):
    def test_ai_advances_to_an_interactive_or_timed_boundary(self) -> None:
        repository = InMemoryRoomRepository()
        created, session, _mutation = start_with_ai(repository)
        snapshot = repository.snapshot_for_access(
            repository._rooms[created.room_id],
            session.access,
        )

        self.assertIn(
            snapshot.phase,
            {"DAY_DISCUSSION", "SELF_DESTRUCT", "VOTE", "END"},
        )
        self.assertNotIn(
            snapshot.phase,
            {
                "NIGHT_WOLF_DISCUSSION_R1",
                "NIGHT_WOLF_DISCUSSION_R2",
                "NIGHT_WOLF_KILL",
                "NIGHT_SEER_CHECK",
                "NIGHT_WITCH_ACTION",
            },
        )

    def test_same_seed_and_action_sequence_are_deterministic(self) -> None:
        first_repository = InMemoryRoomRepository()
        second_repository = InMemoryRoomRepository()
        first_room, _first_session, _ = start_with_ai(first_repository, seed=77)
        second_room, _second_session, _ = start_with_ai(second_repository, seed=77)

        def signature(repository: InMemoryRoomRepository, room_id: str):
            state = repository._rooms[room_id].state
            return (
                state.phase,
                state.day,
                [
                    (
                        event.event_type,
                        event.actor_id,
                        event.target_id,
                        event.data,
                    )
                    for event in state.events
                    if event.event_type is not EventType.GAME_CREATED
                ],
            )

        self.assertEqual(
            signature(first_repository, first_room.room_id),
            signature(second_repository, second_room.room_id),
        )

    def test_human_speech_resumes_ai_until_vote(self) -> None:
        repository = InMemoryRoomRepository()
        created = create_seeded_room(repository)
        session = repository.authenticate_player(
            created.room_id,
            created.player_token,
        )
        room = repository._rooms[created.room_id]
        human = next(player for player in room.state.players if player.is_human)
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.DAY_DISCUSSION
            room.state.day_result = DayResult(
                speech_order=["p1", "p2"],
                speech_deadline=230.0,
            )

        repository.execute_action_and_advance_ai(
            session.access,
            ActionRequest(action="speech", content="真人发言"),
            now=200.0,
        )
        snapshot = repository.snapshot_for_access(room, session.access)

        self.assertIn(snapshot.phase, {"VOTE", "SELF_DESTRUCT"})
        if snapshot.phase == "VOTE":
            self.assertIn(
                "vote",
                [action.action for action in snapshot.available_actions],
            )
        self.assertTrue(human.is_alive)

    def test_step_limit_records_failure_without_unbounded_loop(self) -> None:
        repository = InMemoryRoomRepository()
        created = create_seeded_room(repository, seed=1)
        session = repository.authenticate_player(
            created.room_id,
            created.player_token,
        )
        repository.start_night(session.access)
        controller = AIController(repository, max_steps=2)

        result = controller.advance(created.room_id, now=100.0)
        state = repository._rooms[created.room_id].state

        self.assertEqual(result.steps, 2)
        self.assertEqual(result.stopped_reason, "step_limit")
        self.assertTrue(
            any(
                event.event_type is EventType.AI_ACTION_FAILED
                for event in state.events
            )
        )

    def test_action_failure_keeps_phase_and_records_failure(self) -> None:
        repository = InMemoryRoomRepository()
        created = create_seeded_room(repository, seed=1)
        session = repository.authenticate_player(
            created.room_id,
            created.player_token,
        )
        repository.start_night(session.access)
        room = repository._rooms[created.room_id]
        phase_before = room.state.phase
        events_before = len(room.state.events)

        with patch.object(
            repository,
            "execute_action",
            side_effect=RuntimeError("模拟AI动作失败"),
        ):
            result = repository.advance_ai(created.room_id, now=100.0)

        self.assertEqual(result.stopped_reason, "action_failed")
        self.assertEqual(room.state.phase, phase_before)
        self.assertEqual(len(room.state.events), events_before + 1)
        failure = room.state.events[-1]
        self.assertIs(failure.event_type, EventType.AI_ACTION_FAILED)
        self.assertEqual(failure.data["reason"], "模拟AI动作失败")

    def test_witch_action_always_has_target_for_used_potion(self) -> None:
        state = controlled_game(seed=500)
        witch = next(
            player for player in state.players if player.role is Role.WITCH
        )
        state.phase = Phase.NIGHT_WITCH_ACTION
        state.night_result = NightResult()
        view = next(
            action
            for action in available_actions_for_state(
                state,
                witch,
                host_player_id="p1",
            )
            if action.action == "witch_action"
        )
        controller = AIController(object())

        for seed in range(1, 200):
            state.seed = seed
            request = controller._build_request(
                state,
                witch,
                view,
                policy=L0Policy(seed=seed),
            )
            if request.choice == "none":
                self.assertIsNone(request.target_id)
            else:
                self.assertIn(request.target_id, view.target_ids)
