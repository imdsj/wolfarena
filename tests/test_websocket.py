"""WebSocket authentication, visibility, reconnect, and serialization tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest import TestCase

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api import create_app
from backend.game_engine import (
    EventType,
    Visibility,
    append_event,
    get_player,
    start_night,
)
from backend.rooms import InMemoryRoomRepository, OutOfPhaseError


class WebSocketTestBase(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRoomRepository()
        self.app = create_app(self.repository)
        self.client = TestClient(self.app)

    def create_room(
        self,
        *,
        seed: int = 1,
        human_count: int = 1,
        nickname: str = "订书机",
        max_humans: int = 3,
    ) -> dict[str, object]:
        response = self.client.post(
            "/api/rooms",
            json={
                "seed": seed,
                "human_count": human_count,
                "max_humans": max_humans,
                "nickname": nickname,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def join_room(
        self,
        room_id: str,
        nickname: str,
    ) -> dict[str, object]:
        response = self.client.post(
            f"/api/rooms/{room_id}/join",
            json={"nickname": nickname},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def authenticate_player(
        self,
        websocket,
        token: str,
        room_id: str,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        websocket.send_json({"type": "authenticate", "token": token})
        authenticated = websocket.receive_json()
        snapshot = websocket.receive_json()
        phase = websocket.receive_json()

        self.assertEqual(authenticated["type"], "authenticated")
        self.assertEqual(authenticated["room_id"], room_id)
        self.assertEqual(snapshot["type"], "snapshot")
        self.assertEqual(phase["type"], "phase")
        self.assertEqual(phase["event_seq"], snapshot["event_seq"])
        return authenticated, snapshot, phase

    def authenticate_spectator(
        self,
        websocket,
        password: str,
        room_id: str,
    ) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        websocket.send_json(
            {
                "type": "authenticate",
                "spectator_password": password,
            }
        )
        authenticated = websocket.receive_json()
        snapshot = websocket.receive_json()
        phase = websocket.receive_json()

        self.assertEqual(authenticated["type"], "authenticated")
        self.assertEqual(authenticated["viewer"]["kind"], "spectator")
        self.assertEqual(authenticated["room_id"], room_id)
        self.assertEqual(snapshot["type"], "snapshot")
        self.assertEqual(phase["type"], "phase")
        return authenticated, snapshot, phase

    @staticmethod
    def collect_actions(websocket, *, expect_result: bool) -> dict[str, object]:
        events: list[dict[str, object]] = []
        phases: list[dict[str, object]] = []
        result: dict[str, object] | None = None

        while True:
            message = websocket.receive_json()
            if message["type"] == "event":
                events.append(message)
            elif message["type"] == "phase":
                phases.append(message)
                if not expect_result:
                    break
            elif message["type"] == "action_result":
                result = message
                break

        return {
            "events": events,
            "phases": phases,
            "result": result,
        }


class AuthenticationTests(WebSocketTestBase):
    def test_player_authenticates_in_first_message_and_receives_phase(self) -> None:
        room = self.create_room()
        room_id = room["room_id"]
        url = f"/ws/rooms/{room_id}"
        self.assertNotIn(room["player_token"], url)

        with self.client.websocket_connect(url) as websocket:
            authenticated, snapshot, phase = self.authenticate_player(
                websocket,
                room["player_token"],
                room_id,
            )

            self.assertEqual(authenticated["viewer"]["kind"], "player")
            self.assertEqual(snapshot["room"]["viewer"]["seat"], 1)
            self.assertEqual(snapshot["room"]["phase"], "INIT")
            self.assertEqual(phase["phase"], "INIT")
            self.assertEqual(phase["day"], 0)

            websocket.send_json(
                {
                    "type": "authenticate",
                    "token": room["player_token"],
                }
            )
            duplicate = websocket.receive_json()
            self.assertEqual(duplicate["type"], "error")
            self.assertEqual(duplicate["code"], "ALREADY_AUTHENTICATED")

    def test_invalid_token_closes_with_auth_error(self) -> None:
        room = self.create_room()
        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as websocket:
            websocket.send_json(
                {"type": "authenticate", "token": "not-a-real-token"}
            )
            error = websocket.receive_json()
            self.assertEqual(error["code"], "INVALID_PLAYER_TOKEN")
            with self.assertRaises(WebSocketDisconnect) as raised:
                websocket.receive_json()
            self.assertEqual(raised.exception.code, 4401)

    def test_missing_room_closes_with_not_found(self) -> None:
        with self.client.websocket_connect("/ws/rooms/missing-room") as websocket:
            websocket.send_json({"type": "authenticate", "token": "anything"})
            error = websocket.receive_json()
            self.assertEqual(error["code"], "ROOM_NOT_FOUND")
            with self.assertRaises(WebSocketDisconnect) as raised:
                websocket.receive_json()
            self.assertEqual(raised.exception.code, 4404)

    def test_non_auth_first_message_is_rejected(self) -> None:
        room = self.create_room()
        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as websocket:
            websocket.send_json({"type": "action", "action": "start_night"})
            error = websocket.receive_json()
            self.assertEqual(error["code"], "AUTH_REQUIRED")
            with self.assertRaises(WebSocketDisconnect) as raised:
                websocket.receive_json()
            self.assertEqual(raised.exception.code, 4400)

    def test_wrong_spectator_password_is_rejected(self) -> None:
        room = self.create_room()
        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as websocket:
            websocket.send_json(
                {
                    "type": "authenticate",
                    "spectator_password": "wrong-password",
                }
            )
            error = websocket.receive_json()
            self.assertEqual(error["code"], "INVALID_SPECTATOR_PASSWORD")
            with self.assertRaises(WebSocketDisconnect) as raised:
                websocket.receive_json()
            self.assertEqual(raised.exception.code, 4403)

    def test_each_room_has_a_different_spectator_password(self) -> None:
        first = self.create_room(seed=1)
        second = self.create_room(seed=1, nickname="第二房主")

        self.assertNotEqual(
            first["spectator_password"],
            second["spectator_password"],
        )


class VisibilityTests(WebSocketTestBase):
    def test_public_snapshot_hides_wolf_speech_and_death_causes(self) -> None:
        room = self.create_room(seed=1)
        access_room = self.repository._rooms[room["room_id"]]

        with access_room.lock:
            start_night(access_room.state)
            wolf = next(
                player
                for player in access_room.state.players
                if player.role.value == "werewolf"
            )
            append_event(
                access_room.state,
                EventType.WOLF_SPEECH,
                actor_id=wolf.player_id,
                visibility=Visibility.WOLVES,
                data={"round": 1, "content": "先刀预言家"},
            )
            append_event(
                access_room.state,
                EventType.PLAYER_DIED,
                target_id=get_player(access_room.state, "p1").player_id,
                visibility=Visibility.PUBLIC,
                data={"causes": ["wolf_kill"]},
            )

        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as player_socket:
            _, snapshot_message, _ = self.authenticate_player(
                player_socket,
                room["player_token"],
                room["room_id"],
            )
            events = snapshot_message["room"]["visible_events"]
            self.assertNotIn(
                "WOLF_SPEECH",
                {event["event_type"] for event in events},
            )
            death_events = [
                event
                for event in events
                if event["event_type"] == "PLAYER_DIED"
            ]
            self.assertEqual(len(death_events), 1)
            self.assertNotIn("causes", death_events[0]["data"])

        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as spectator_socket:
            _, spectator_snapshot, _ = self.authenticate_spectator(
                spectator_socket,
                room["spectator_password"],
                room["room_id"],
            )
            spectator_events = spectator_snapshot["room"]["visible_events"]
            self.assertIn(
                "WOLF_SPEECH",
                {event["event_type"] for event in spectator_events},
            )
            spectator_deaths = [
                event
                for event in spectator_events
                if event["event_type"] == "PLAYER_DIED"
            ]
            self.assertEqual(
                spectator_deaths[0]["data"]["causes"],
                ["wolf_kill"],
            )

    def test_wolf_living_player_and_spectator_receive_different_events(self) -> None:
        room = self.create_room(seed=3, human_count=3, nickname="WolfHost")
        joined = self.join_room(room["room_id"], "GoodPlayer")
        self.assertEqual(room["room"]["viewer"]["role"], "werewolf")
        self.assertEqual(joined["room"]["viewer"]["role"], "villager")

        url = f"/ws/rooms/{room['room_id']}"
        with (
            self.client.websocket_connect(url) as wolf_socket,
            self.client.websocket_connect(url) as good_socket,
            self.client.websocket_connect(url) as spectator_socket,
        ):
            self.authenticate_player(
                wolf_socket,
                room["player_token"],
                room["room_id"],
            )
            self.authenticate_player(
                good_socket,
                joined["player_token"],
                room["room_id"],
            )
            self.authenticate_spectator(
                spectator_socket,
                room["spectator_password"],
                room["room_id"],
            )

            wolf_socket.send_json({"type": "action", "action": "start_night"})
            wolf_messages = self.collect_actions(
                wolf_socket,
                expect_result=True,
            )
            good_messages = self.collect_actions(
                good_socket,
                expect_result=False,
            )
            spectator_messages = self.collect_actions(
                spectator_socket,
                expect_result=False,
            )

        wolf_events = wolf_messages["events"]
        good_events = good_messages["events"]
        spectator_events = spectator_messages["events"]

        self.assertEqual(
            {event["event_type"] for event in wolf_events},
            {"WOLF_CAPTAIN_ELECTED", "NIGHT_STARTED"},
        )
        self.assertEqual(
            {event["event_type"] for event in good_events},
            {"NIGHT_STARTED"},
        )
        self.assertEqual(
            {event["event_type"] for event in spectator_events},
            {"WOLF_CAPTAIN_ELECTED", "NIGHT_STARTED"},
        )
        wolf_sequences = [event["event_seq"] for event in wolf_events]
        self.assertEqual(wolf_sequences, sorted(set(wolf_sequences)))
        self.assertEqual(wolf_messages["phases"][0]["phase"], "NIGHT_WOLF_DISCUSSION_R1")
        self.assertTrue(wolf_messages["result"]["ok"])

    def test_dead_wolf_reconnect_does_not_receive_wolf_view(self) -> None:
        room = self.create_room(seed=3)
        access_room = self.repository._rooms[room["room_id"]]
        with access_room.lock:
            wolf = get_player(access_room.state, "p1")
            self.assertEqual(wolf.role.value, "werewolf")
            wolf.is_alive = False
            append_event(
                access_room.state,
                EventType.WOLF_SPEECH,
                actor_id=wolf.player_id,
                visibility=Visibility.WOLVES,
                data={"round": 1, "content": "死亡后不应看到"},
            )

        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as websocket:
            _, snapshot, _ = self.authenticate_player(
                websocket,
                room["player_token"],
                room["room_id"],
            )

        self.assertFalse(snapshot["room"]["viewer"]["is_alive"])
        self.assertNotIn(
            "WOLF_SPEECH",
            {
                event["event_type"]
                for event in snapshot["room"]["visible_events"]
            },
        )


class ReconnectAndActionTests(WebSocketTestBase):
    def test_existing_player_receives_updated_snapshot_after_join(self) -> None:
        room = self.create_room(seed=1)
        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as host_socket:
            self.authenticate_player(
                host_socket,
                room["player_token"],
                room["room_id"],
            )
            self.join_room(room["room_id"], "SecondPlayer")

            messages = []
            while True:
                message = host_socket.receive_json()
                messages.append(message)
                if message["type"] == "snapshot":
                    break

        event_types = [
            message["event_type"]
            for message in messages
            if message["type"] == "event"
        ]
        snapshot = messages[-1]["room"]
        self.assertIn("PLAYER_JOINED", event_types)
        self.assertEqual(snapshot["human_count"], 2)
        self.assertEqual(
            sum(player["is_human"] for player in snapshot["players"]),
            2,
        )

    def test_reconnect_keeps_seat_and_current_phase(self) -> None:
        room = self.create_room(seed=1)
        url = f"/ws/rooms/{room['room_id']}"

        with self.client.websocket_connect(url) as websocket:
            _, first_snapshot, _ = self.authenticate_player(
                websocket,
                room["player_token"],
                room["room_id"],
            )
            websocket.send_json({"type": "action", "action": "start_night"})
            messages = self.collect_actions(websocket, expect_result=True)
            self.assertTrue(messages["result"]["ok"])

        with self.client.websocket_connect(url) as websocket:
            _, second_snapshot, phase = self.authenticate_player(
                websocket,
                room["player_token"],
                room["room_id"],
            )

        self.assertEqual(
            first_snapshot["room"]["viewer"]["seat"],
            second_snapshot["room"]["viewer"]["seat"],
        )
        self.assertNotIn(phase["phase"], {"INIT"})
        self.assertEqual(second_snapshot["room"]["day"], 1)

    def test_action_outside_phase_returns_error_without_mutation(self) -> None:
        room = self.create_room(seed=1)
        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as websocket:
            self.authenticate_player(
                websocket,
                room["player_token"],
                room["room_id"],
            )
            websocket.send_json({"type": "action", "action": "start_night"})
            self.collect_actions(websocket, expect_result=True)
            websocket.send_json({"type": "action", "action": "start_night"})
            error = websocket.receive_json()

        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "ACTION_UNAVAILABLE")

    def test_spectator_cannot_control_game(self) -> None:
        room = self.create_room()
        with self.client.websocket_connect(
            f"/ws/rooms/{room['room_id']}"
        ) as websocket:
            self.authenticate_spectator(
                websocket,
                room["spectator_password"],
                room["room_id"],
            )
            websocket.send_json({"type": "action", "action": "start_night"})
            error = websocket.receive_json()

        self.assertEqual(error["code"], "ACTION_FORBIDDEN")

    def test_concurrent_start_actions_are_serialized(self) -> None:
        room = self.create_room(seed=1)
        repository = self.app.state.rooms
        session = repository.authenticate_player(
            room["room_id"],
            room["player_token"],
        )

        def begin_night() -> str:
            try:
                repository.start_night(session.access)
                return "ok"
            except OutOfPhaseError:
                return "out_of_phase"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: begin_night(), range(2)))

        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("out_of_phase"), 1)

    def test_join_is_closed_after_game_start(self) -> None:
        room = self.create_room(seed=1, human_count=1)
        session = self.repository.authenticate_player(
            room["room_id"],
            room["player_token"],
        )
        self.repository.start_night(session.access)

        response = self.client.post(
            f"/api/rooms/{room['room_id']}/join",
            json={"nickname": "迟到玩家"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "JOIN_CLOSED")
