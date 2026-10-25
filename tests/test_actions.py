"""Unified action catalog, validation, and dispatch tests."""

from __future__ import annotations

from copy import deepcopy
from unittest import TestCase

from fastapi.testclient import TestClient

from backend.actions import (
    ActionValidationError,
    available_actions_for_state,
    execute_engine_action,
)
from backend.api import create_app
from backend.game_engine import (
    Phase,
    Role,
    get_player,
)
from backend.rooms import InMemoryRoomRepository
from backend.schemas import ActionRequest
from tests.test_game_engine import controlled_game


class ActionCatalogTests(TestCase):
    def test_init_phase_exposes_only_host_start_action(self) -> None:
        state = controlled_game(seed=401)
        host = get_player(state, "p1")

        actions = available_actions_for_state(
            state,
            host,
            host_player_id=host.player_id,
        )

        self.assertEqual([action.action for action in actions], ["start_night"])

    def test_wolf_speech_follows_server_side_seat_order(self) -> None:
        state = controlled_game(seed=402)
        host = get_player(state, "p1")
        execute_engine_action(
            state,
            host,
            ActionRequest(action="start_night"),
            host_player_id=host.player_id,
        )

        first = available_actions_for_state(
            state,
            get_player(state, "p1"),
            host_player_id=host.player_id,
        )
        second = available_actions_for_state(
            state,
            get_player(state, "p2"),
            host_player_id=host.player_id,
        )
        self.assertEqual([item.action for item in first], ["wolf_speech"])
        self.assertEqual(second, ())

        execute_engine_action(
            state,
            get_player(state, "p1"),
            ActionRequest(action="wolf_speech", content="第一轮 P1"),
            host_player_id=host.player_id,
        )
        second = available_actions_for_state(
            state,
            get_player(state, "p2"),
            host_player_id=host.player_id,
        )
        self.assertEqual([item.action for item in second], ["wolf_speech"])

    def test_full_public_day_reaches_vote_and_next_night(self) -> None:
        state = controlled_game(seed=403)
        host = get_player(state, "p1")
        host_id = host.player_id
        execute_engine_action(
            state,
            host,
            ActionRequest(action="start_night"),
            host_player_id=host_id,
        )

        wolves = sorted(
            (
                player
                for player in state.players
                if player.role is Role.WEREWOLF and player.is_alive
            ),
            key=lambda player: player.seat,
        )
        for round_number in (1, 2):
            for wolf in wolves:
                execute_engine_action(
                    state,
                    wolf,
                    ActionRequest(
                        action="wolf_speech",
                        content=f"R{round_number}-{wolf.seat}",
                    ),
                    host_player_id=host_id,
                )

        captain = get_player(state, state.wolf_captain_id)
        execute_engine_action(
            state,
            captain,
            ActionRequest(action="wolf_kill"),
            host_player_id=host_id,
        )
        seer = next(
            player for player in state.players if player.role is Role.SEER
        )
        target = next(
            player
            for player in state.players
            if player.role is Role.VILLAGER and player.is_alive
        )
        execute_engine_action(
            state,
            seer,
            ActionRequest(action="seer_check", target_id=target.player_id),
            host_player_id=host_id,
        )
        witch = next(
            player for player in state.players if player.role is Role.WITCH
        )
        execute_engine_action(
            state,
            witch,
            ActionRequest(action="witch_action", choice="none"),
            host_player_id=host_id,
        )
        execute_engine_action(
            state,
            host,
            ActionRequest(action="resolve_night"),
            host_player_id=host_id,
        )
        self.assertIs(state.phase, Phase.DAY_ANNOUNCEMENT)

        execute_engine_action(
            state,
            host,
            ActionRequest(action="begin_day"),
            host_player_id=host_id,
        )
        self.assertIs(state.phase, Phase.DAY_DISCUSSION)

        order = list(state.day_result.speech_order)
        for player_id in order:
            player = get_player(state, player_id)
            execute_engine_action(
                state,
                player,
                ActionRequest(action="speech", content=f"发言-{player.seat}"),
                host_player_id=host_id,
            )
        self.assertIs(state.phase, Phase.VOTE)

        for player in state.players:
            if player.is_alive:
                execute_engine_action(
                    state,
                    player,
                    ActionRequest(action="vote"),
                    host_player_id=host_id,
                )
        execute_engine_action(
            state,
            host,
            ActionRequest(action="close_vote"),
            host_player_id=host_id,
        )
        execute_engine_action(
            state,
            host,
            ActionRequest(action="resolve_vote"),
            host_player_id=host_id,
        )

        self.assertIs(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        self.assertEqual(state.day, 2)

    def test_invalid_target_is_rejected_before_engine(self) -> None:
        state = controlled_game(seed=404)
        before = deepcopy(state)
        host = get_player(state, "p1")

        with self.assertRaises(ActionValidationError):
            execute_engine_action(
                state,
                host,
                ActionRequest(action="start_night", target_id="p9"),
                host_player_id=host.player_id,
            )

        self.assertEqual(state.phase, before.phase)
        self.assertEqual(len(state.events), len(before.events))


class ActionApiTests(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRoomRepository()
        self.client = TestClient(create_app(self.repository))
        response = self.client.post(
            "/api/rooms",
            json={
                "seed": 1,
                "human_count": 1,
                "max_humans": 3,
                "nickname": "订书机",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.room = response.json()

    def post_action(self, action: str, **extra: object):
        return self.client.post(
            f"/api/rooms/{self.room['room_id']}/actions",
            headers={"X-Player-Token": self.room["player_token"]},
            json={"action": action, **extra},
        )

    def test_snapshot_exposes_current_host_action(self) -> None:
        self.assertEqual(
            [item["action"] for item in self.room["room"]["available_actions"]],
            ["start_night"],
        )

    def test_http_action_uses_same_engine_and_advances_phase(self) -> None:
        response = self.post_action("start_night")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["phase"], "DAY_DISCUSSION")
        again = self.post_action("start_night")
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.json()["detail"]["code"], "ACTION_UNAVAILABLE")

    def test_invalid_target_returns_422_without_state_change(self) -> None:
        response = self.post_action("start_night", target_id="p9")
        snapshot = self.client.get(
            f"/api/rooms/{self.room['room_id']}",
            headers={"X-Player-Token": self.room["player_token"]},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "ACTION_INVALID")
        self.assertEqual(snapshot.json()["phase"], "INIT")
