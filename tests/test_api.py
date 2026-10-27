"""Acceptance tests for the first FastAPI and in-memory room slice."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.rooms import InMemoryRoomRepository


class ApiHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(InMemoryRoomRepository()))

    def test_health_is_parseable_and_has_no_sensitive_configuration(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "service": "wolfarena-api",
                "version": "0.6.0",
            },
        )
        lowered = response.text.lower()
        for forbidden in ("api_key", "secret", "password", "c:\\"):
            self.assertNotIn(forbidden, lowered)


class RoomCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(InMemoryRoomRepository()))

    def create_room(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "seed": 20261025,
            "human_count": 1,
            "nickname": "订书机",
        }
        payload.update(overrides)
        response = self.client.post("/api/rooms", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_create_room_returns_one_human_and_eight_ai(self) -> None:
        body = self.create_room()
        room = body["room"]

        self.assertTrue(body["room_id"])
        self.assertTrue(body["player_token"])
        self.assertEqual(room["phase"], "INIT")
        self.assertEqual(room["human_count"], 1)
        self.assertEqual(room["max_humans"], 3)
        self.assertEqual(len(room["players"]), 9)
        self.assertEqual(
            sum(player["is_human"] for player in room["players"]),
            1,
        )
        self.assertEqual(
            sum(not player["is_human"] for player in room["players"]),
            8,
        )
        self.assertEqual(room["viewer"]["name"], "订书机")
        self.assertIn(
            room["viewer"]["role"],
            {"werewolf", "villager", "seer", "witch", "hunter"},
        )

    def test_create_room_is_reproducible_for_the_same_seed(self) -> None:
        first = self.create_room(seed=77)
        second = self.create_room(seed=77, nickname="第二位房主")

        self.assertEqual(
            first["room"]["viewer"]["role"],
            second["room"]["viewer"]["role"],
        )

    def test_live_room_may_use_server_generated_seed(self) -> None:
        response = self.client.post(
            "/api/rooms",
            json={
                "human_count": 1,
                "max_humans": 3,
                "nickname": "服务端随机房主",
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["room"]["phase"], "INIT")

    def test_create_room_rejects_invalid_human_limits(self) -> None:
        for value in (0, 4):
            with self.subTest(value=value):
                response = self.client.post(
                    "/api/rooms",
                    json={
                        "seed": 1,
                        "human_count": value,
                        "nickname": "房主",
                    },
                )
                self.assertEqual(response.status_code, 422)

        for value in (0, 4):
            with self.subTest(max_humans=value):
                response = self.client.post(
                    "/api/rooms",
                    json={
                        "seed": 1,
                        "human_count": 1,
                        "max_humans": value,
                        "nickname": "房主",
                    },
                )
                self.assertEqual(response.status_code, 422)

    def test_supported_human_limits_are_accepted(self) -> None:
        for value in (1, 3):
            with self.subTest(human_count=value):
                body = self.create_room(human_count=value, max_humans=value)
                self.assertEqual(body["room"]["max_humans"], value)

    def test_creating_with_more_initial_humans_than_room_limit_is_rejected(
        self,
    ) -> None:
        response = self.client.post(
            "/api/rooms",
            json={
                "seed": 1,
                "human_count": 2,
                "max_humans": 1,
                "nickname": "房主",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "INVALID_ROOM_CONFIG")

    def test_good_player_only_sees_their_own_role(self) -> None:
        body = self.create_room(seed=1)
        token = body["player_token"]
        room_id = body["room_id"]

        response = self.client.get(
            f"/api/rooms/{room_id}",
            headers={"X-Player-Token": token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        room = response.json()

        self.assertIn("role", room["viewer"])
        self.assertTrue(room["players"])
        for player in room["players"]:
            self.assertNotIn("role", player)

        role_events = [
            event
            for event in room["visible_events"]
            if event["event_type"] == "ROLE_ASSIGNED"
        ]
        self.assertEqual(len(role_events), 1)
        self.assertEqual(role_events[0]["target_id"], room["viewer"]["player_id"])

    def test_wolf_player_only_sees_wolf_roles(self) -> None:
        for seed in range(1, 100):
            body = self.create_room(seed=seed)
            if body["room"]["viewer"]["role"] == "werewolf":
                break
        else:
            self.fail("未找到狼人视角测试种子")

        response = self.client.get(
            f"/api/rooms/{body['room_id']}",
            headers={"X-Player-Token": body["player_token"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        room = response.json()

        role_events = [
            event
            for event in room["visible_events"]
            if event["event_type"] == "ROLE_ASSIGNED"
        ]
        self.assertEqual(len(role_events), 3)
        self.assertEqual(
            {event["data"]["role"] for event in role_events},
            {"werewolf"},
        )

    def test_get_room_requires_a_valid_player_token(self) -> None:
        body = self.create_room()
        room_id = body["room_id"]

        missing = self.client.get(f"/api/rooms/{room_id}")
        invalid = self.client.get(
            f"/api/rooms/{room_id}",
            headers={"X-Player-Token": "not-a-real-token"},
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(missing.json()["detail"]["code"], "INVALID_PLAYER_TOKEN")


class RoomJoinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(InMemoryRoomRepository()))

    def create_room(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "seed": 20261025,
            "human_count": 1,
            "nickname": "订书机",
        }
        payload.update(overrides)
        response = self.client.post("/api/rooms", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def join(self, room_id: str, nickname: str) -> object:
        return self.client.post(
            f"/api/rooms/{room_id}/join",
            json={"nickname": nickname},
        )

    def test_default_room_allows_three_humans_and_rejects_the_fourth(self) -> None:
        created = self.create_room()
        room_id = created["room_id"]

        second = self.join(room_id, "Hurry")
        third = self.join(room_id, "祁楷")
        fourth = self.join(room_id, "第四人")

        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(third.status_code, 200, third.text)
        self.assertEqual(third.json()["room"]["human_count"], 3)
        self.assertEqual(fourth.status_code, 409)
        self.assertEqual(fourth.json()["detail"]["code"], "ROOM_FULL")

    def test_explicit_two_human_limit_rejects_the_third(self) -> None:
        created = self.create_room(max_humans=2)
        room_id = created["room_id"]

        second = self.join(room_id, "Hurry")
        third = self.join(room_id, "祁楷")

        self.assertEqual(second.status_code, 200)
        self.assertEqual(third.status_code, 409)
        self.assertEqual(third.json()["detail"]["code"], "ROOM_FULL")

    def test_duplicate_nickname_and_unknown_room_are_rejected(self) -> None:
        created = self.create_room()
        room_id = created["room_id"]

        duplicate = self.join(room_id, "订书机")
        unknown = self.join("missing-room", "Hurry")

        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json()["detail"]["code"], "DUPLICATE_NICKNAME")
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(unknown.json()["detail"]["code"], "ROOM_NOT_FOUND")

    def test_second_human_receives_their_own_role_only(self) -> None:
        created = self.create_room()
        joined = self.join(created["room_id"], "Hurry")
        self.assertEqual(joined.status_code, 200, joined.text)

        body = joined.json()
        room = body["room"]
        self.assertEqual(room["viewer"]["name"], "Hurry")
        self.assertEqual(room["human_count"], 2)
        self.assertEqual(room["viewer"]["player_id"], "p2")
        self.assertTrue(all("role" not in player for player in room["players"]))

        role_events = [
            event
            for event in room["visible_events"]
            if event["event_type"] == "ROLE_ASSIGNED"
        ]
        self.assertEqual(len(role_events), 1)
        self.assertEqual(role_events[0]["target_id"], "p2")

    def test_reserved_human_seat_is_used_before_ai_seat(self) -> None:
        created = self.create_room(human_count=2)
        joined = self.join(created["room_id"], "Hurry")

        self.assertEqual(joined.status_code, 200, joined.text)
        self.assertEqual(joined.json()["room"]["viewer"]["player_id"], "p2")


if __name__ == "__main__":
    unittest.main()
