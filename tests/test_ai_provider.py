"""Deterministic tests for DeepSeek adaptation and fallback behavior."""

from __future__ import annotations

import json
import unittest

import httpx
from fastapi.testclient import TestClient

from backend.ai_provider import (
    AIDecision,
    CandidateAction,
    DeepSeekCandidateProvider,
    DeepSeekSettings,
)
from backend.api import create_app
from backend.rooms import InMemoryRoomRepository


def model_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": content,
                    }
                }
            ]
        },
    )


def candidate_json(
    *,
    action: str = "start_night",
    target_id: str | None = None,
) -> str:
    return json.dumps(
        {
            "action": action,
            "target_id": target_id,
            "content": None,
            "confidence": 0.8,
            "reason": "服务端允许开始首夜",
        },
        ensure_ascii=False,
    )


class StaticProvider:
    def __init__(self, decision: AIDecision) -> None:
        self.decision = decision

    async def propose(
        self,
        snapshot,
        *,
        legal_actions,
        valid_target_ids,
    ) -> AIDecision:
        return self.decision


class DeepSeekProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRoomRepository()
        created = self.repository.create_room(
            seed=1,
            human_count=1,
            max_humans=3,
            nickname="订书机",
        )
        self.session = self.repository.authenticate_player(
            created.room_id,
            created.player_token,
        )
        self.context = self.repository.ai_action_context(self.session.access)

    async def test_missing_key_uses_fallback_without_network(self) -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return model_response(candidate_json())

        provider = DeepSeekCandidateProvider(
            DeepSeekSettings(api_key=None),
            transport=httpx.MockTransport(handler),
        )
        decision = await provider.propose(
            self.context.snapshot,
            legal_actions=self.context.legal_actions,
            valid_target_ids=self.context.valid_target_ids,
        )

        self.assertEqual(calls, 0)
        self.assertEqual(decision.source, "fallback")
        self.assertEqual(decision.fallback_reason, "missing_api_key")
        self.assertEqual(decision.candidate.action, "start_night")

    async def test_valid_json_is_validated_and_uses_auth_header(self) -> None:
        observed_authorization = []

        async def handler(request: httpx.Request) -> httpx.Response:
            observed_authorization.append(request.headers.get("authorization"))
            return model_response(candidate_json())

        provider = DeepSeekCandidateProvider(
            DeepSeekSettings(api_key="test-secret-key"),
            transport=httpx.MockTransport(handler),
        )
        decision = await provider.propose(
            self.context.snapshot,
            legal_actions=self.context.legal_actions,
            valid_target_ids=self.context.valid_target_ids,
        )

        self.assertEqual(decision.source, "deepseek")
        self.assertEqual(decision.attempts, 1)
        self.assertEqual(decision.candidate.action, "start_night")
        self.assertEqual(
            observed_authorization,
            ["Bearer test-secret-key"],
        )

    async def test_invalid_json_requests_exactly_one_repair(self) -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return model_response("这不是 JSON")
            return model_response(candidate_json())

        provider = DeepSeekCandidateProvider(
            DeepSeekSettings(api_key="test-secret-key"),
            transport=httpx.MockTransport(handler),
        )
        with self.assertLogs("backend.ai_provider", level="WARNING") as logs:
            decision = await provider.propose(
                self.context.snapshot,
                legal_actions=self.context.legal_actions,
                valid_target_ids=self.context.valid_target_ids,
            )

        self.assertEqual(calls, 2)
        self.assertEqual(decision.source, "repair")
        self.assertEqual(decision.attempts, 2)
        self.assertNotIn("test-secret-key", "\n".join(logs.output))
        self.assertNotIn("Authorization", "\n".join(logs.output))

    async def test_invalid_json_twice_falls_back(self) -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return model_response("仍然不是 JSON")

        provider = DeepSeekCandidateProvider(
            DeepSeekSettings(api_key="test-secret-key"),
            transport=httpx.MockTransport(handler),
        )
        decision = await provider.propose(
            self.context.snapshot,
            legal_actions=self.context.legal_actions,
            valid_target_ids=self.context.valid_target_ids,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(decision.source, "fallback")
        self.assertEqual(decision.attempts, 2)
        self.assertEqual(decision.fallback_reason, "invalid_json")

    async def test_timeout_retries_once_then_falls_back(self) -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("timeout", request=request)

        provider = DeepSeekCandidateProvider(
            DeepSeekSettings(api_key="test-secret-key"),
            transport=httpx.MockTransport(handler),
        )
        decision = await provider.propose(
            self.context.snapshot,
            legal_actions=self.context.legal_actions,
            valid_target_ids=self.context.valid_target_ids,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(decision.source, "fallback")
        self.assertEqual(decision.attempts, 2)
        self.assertTrue(decision.fallback_reason.startswith("model_"))

    async def test_unexpected_fields_are_rejected_then_repaired(self) -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return model_response(
                    '{"action":"start_night","reason":"x","dangerous":true}'
                )
            return model_response(candidate_json())

        provider = DeepSeekCandidateProvider(
            DeepSeekSettings(api_key="test-secret-key"),
            transport=httpx.MockTransport(handler),
        )
        decision = await provider.propose(
            self.context.snapshot,
            legal_actions=self.context.legal_actions,
            valid_target_ids=self.context.valid_target_ids,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(decision.source, "repair")


class AIActionEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryRoomRepository()

    def create_client(self, provider=None) -> tuple[TestClient, dict[str, object]]:
        client = TestClient(
            create_app(self.repository, ai_provider=provider)
        )
        response = client.post(
            "/api/rooms",
            json={
                "seed": 1,
                "human_count": 1,
                "nickname": "订书机",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return client, response.json()

    @staticmethod
    def decision(
        *,
        action: str = "start_night",
        target_id: str | None = None,
        source: str = "deepseek",
    ) -> AIDecision:
        return AIDecision(
            candidate=CandidateAction(
                action=action,
                target_id=target_id,
                confidence=0.9,
                reason="测试候选",
            ),
            source=source,
            attempts=1,
        )

    def ai_request(self, client: TestClient, room: dict[str, object]):
        return client.post(
            f"/api/rooms/{room['room_id']}/ai-action",
            headers={"X-Player-Token": room["player_token"]},
        )

    def get_room(self, client: TestClient, room: dict[str, object]):
        return client.get(
            f"/api/rooms/{room['room_id']}",
            headers={"X-Player-Token": room["player_token"]},
        )

    def test_valid_candidate_executes_through_rules_engine(self) -> None:
        client, room = self.create_client(StaticProvider(self.decision()))

        response = self.ai_request(client, room)

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["executed"])
        self.assertNotEqual(body["phase"], "INIT")

    def test_no_key_fallback_executes_and_records_event(self) -> None:
        provider = DeepSeekCandidateProvider(DeepSeekSettings(api_key=None))
        client, room = self.create_client(provider)

        response = self.ai_request(client, room)
        snapshot = self.get_room(client, room).json()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"]["source"], "fallback")
        self.assertNotEqual(snapshot["phase"], "INIT")
        fallback_events = [
            event
            for event in snapshot["visible_events"]
            if event["event_type"] == "AI_FALLBACK_USED"
        ]
        self.assertEqual(len(fallback_events), 1)
        self.assertEqual(
            fallback_events[0]["data"]["reason"],
            "missing_api_key",
        )

    def test_timeout_fallback_still_advances_the_game(self) -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("timeout", request=request)

        provider = DeepSeekCandidateProvider(
            DeepSeekSettings(api_key="test-secret-key"),
            transport=httpx.MockTransport(handler),
        )
        client, room = self.create_client(provider)

        response = self.ai_request(client, room)
        snapshot = self.get_room(client, room).json()

        self.assertEqual(calls, 2)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["decision"]["source"], "fallback")
        self.assertNotEqual(response.json()["phase"], "INIT")
        self.assertEqual(snapshot["phase"], response.json()["phase"])

    def test_illegal_action_is_rejected_without_phase_change(self) -> None:
        client, room = self.create_client(
            StaticProvider(self.decision(action="drop_database"))
        )

        response = self.ai_request(client, room)
        snapshot = self.get_room(client, room).json()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "AI_ACTION_INVALID")
        self.assertEqual(snapshot["phase"], "INIT")
        rejection_events = [
            event
            for event in snapshot["visible_events"]
            if event["event_type"] == "AI_ACTION_REJECTED"
        ]
        self.assertEqual(len(rejection_events), 1)
        self.assertEqual(
            rejection_events[0]["data"]["reason"],
            "action_not_legal",
        )

    def test_illegal_target_is_rejected_without_phase_change(self) -> None:
        client, room = self.create_client(
            StaticProvider(self.decision(target_id="p999"))
        )

        response = self.ai_request(client, room)
        snapshot = self.get_room(client, room).json()

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "AI_TARGET_INVALID")
        self.assertEqual(snapshot["phase"], "INIT")
        rejection_events = [
            event
            for event in snapshot["visible_events"]
            if event["event_type"] == "AI_ACTION_REJECTED"
        ]
        self.assertEqual(len(rejection_events), 1)
        self.assertEqual(
            rejection_events[0]["data"]["reason"],
            "target_not_valid",
        )
