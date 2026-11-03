"""Tests for the room chat endpoint that lets a player talk to an AI seat."""

from __future__ import annotations

from unittest import TestCase

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.rooms import InMemoryRoomRepository


class FakeProvider:
    def __init__(self, reply: str = "收到，我会考虑你的说法。", fail: bool = False):
        self.reply = reply
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def propose(self, *args, **kwargs):
        raise NotImplementedError

    async def chat_reply(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("model down")
        return self.reply


class RoomChatTests(TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRoomRepository()
        self.provider = FakeProvider()
        self.client = TestClient(
            create_app(self.repository, ai_provider=self.provider)
        )
        response = self.client.post(
            "/api/rooms",
            json={"nickname": "host", "human_count": 1, "max_humans": 3},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.room = response.json()

    def chat(self, message: str, seat: int | None = None, token=None):
        body: dict[str, object] = {"message": message}
        if seat is not None:
            body["seat"] = seat
        return self.client.post(
            f"/api/rooms/{self.room['room_id']}/chat",
            json=body,
            headers={"X-Player-Token": token or self.room["player_token"]},
        )

    def test_ai_replies_with_model_text(self) -> None:
        response = self.chat("你好，你怎么看 5 号？")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["reply"], "收到，我会考虑你的说法。")
        self.assertEqual(body["source"], "deepseek")
        self.assertIn("seat", body)

    def test_provider_failure_falls_back_without_state_change(self) -> None:
        self.provider.fail = True
        response = self.chat("你在吗？")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source"], "fallback")
        self.assertTrue(body["reply"])

    def test_prompt_only_contains_public_information(self) -> None:
        self.chat("5 号是不是狼？", seat=3)
        call = self.provider.calls[-1]
        roster = call["roster"]
        self.assertTrue(roster)
        for entry in roster:
            self.assertRegex(entry, r"^\d+号")
            self.assertNotIn("werewolf", entry)
            self.assertNotIn("预言家", entry)
        self.assertEqual(call["seat"], 3)

    def test_rate_limit_rejects_back_to_back_messages(self) -> None:
        self.assertEqual(self.chat("第一句").status_code, 200)
        self.assertEqual(self.chat("第二句").status_code, 429)

    def test_missing_token_and_long_message_are_rejected(self) -> None:
        self.assertEqual(self.chat("hi", token="bad-token").status_code, 401)
        self.assertEqual(self.chat("x" * 201).status_code, 422)
