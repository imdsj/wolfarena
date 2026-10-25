"""End-to-end acceptance through the same actions used by the web client."""

from __future__ import annotations

from unittest import TestCase

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.rooms import InMemoryRoomRepository


ACTION_PRIORITY = (
    "start_night",
    "speech",
    "last_words",
    "wolf_speech",
    "seer_check",
    "witch_action",
    "vote",
    "close_vote",
    "resolve_vote",
    "begin_banishment_last_words",
    "wolf_kill",
    "night_hunter_shot",
    "day_hunter_shot",
    "resolve_night",
    "begin_day",
    "close_self_destruct_window",
)


class WebGameEndToEndTests(TestCase):
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
        self.created = response.json()
        self.room_id = self.created["room_id"]
        self.token = self.created["player_token"]
        self.voted_days: set[int] = set()

    def snapshot(self) -> dict[str, object]:
        response = self.client.get(
            f"/api/rooms/{self.room_id}",
            headers={"X-Player-Token": self.token},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def choose_action(
        self,
        snapshot: dict[str, object],
    ) -> dict[str, object] | None:
        actions = {
            action["action"]: action
            for action in snapshot["available_actions"]
        }
        for name in ACTION_PRIORITY:
            if name not in actions:
                continue
            if name == "vote" and snapshot["day"] in self.voted_days:
                continue
            view = actions[name]
            target_id = None
            if view["requires_target"]:
                self.assertTrue(view["target_ids"])
                target_id = view["target_ids"][0]
            content = None
            if view["requires_content"]:
                content = f"真人测试行动-{name}"
            choice = view["choices"][0] if view["choices"] else None
            if name == "witch_action":
                choice = "none"
                target_id = None
            if name == "vote":
                self.voted_days.add(snapshot["day"])
            return {
                "action": name,
                "target_id": target_id,
                "content": content,
                "choice": choice,
            }
        return None

    def test_one_human_can_reach_end_through_public_action_api(self) -> None:
        snapshot = self.snapshot()
        phases: list[str] = [snapshot["phase"]]
        history: list[str] = []

        for _step in range(2000):
            if snapshot["phase"] == "END":
                break
            request = self.choose_action(snapshot)
            if request is None:
                room = self.repository._rooms[self.room_id]
                with room.lock:
                    deadline = (
                        room.state.day_result.self_destruct_deadline
                        if room.state.phase.value == "SELF_DESTRUCT"
                        and room.state.day_result is not None
                        else None
                    )
                if deadline is not None:
                    self.repository.process_expired_deadlines(deadline)

                # A completed AI/system turn should produce a fresh boundary.
                next_snapshot = self.snapshot()
                def progress_key(value: dict[str, object]):
                    return (
                        value["phase"],
                        value["day"],
                        value["available_actions"],
                        value["viewer"],
                    )

                if progress_key(next_snapshot) == progress_key(snapshot):
                    self.fail(
                        "真人无合法动作且阶段停滞："
                        f"{snapshot['phase']}，第 {snapshot['day']} 天，"
                        f"动作 {snapshot['available_actions']}；"
                        f"最近动作：{history[-20:]}"
                    )
                snapshot = next_snapshot
                phases.append(snapshot["phase"])
                continue

            history.append(f"{snapshot['day']}:{snapshot['phase']}:{request['action']}")
            response = self.client.post(
                f"/api/rooms/{self.room_id}/actions",
                headers={"X-Player-Token": self.token},
                json=request,
            )
            self.assertEqual(
                response.status_code,
                200,
                f"{request['action']} @ {snapshot['phase']}: {response.text}",
            )
            snapshot = response.json()
            if snapshot["phase"] != phases[-1]:
                phases.append(snapshot["phase"])
        else:
            self.fail(
                "2000 个动作步内仍未从 INIT 到达 END；"
                f"最近动作：{history[-40:]}"
            )

        self.assertEqual(snapshot["phase"], "END")
        self.assertTrue(phases)
        self.assertEqual(phases[0], "INIT")
        self.assertEqual(phases[-1], "END")
        self.assertEqual(self.client.get("/health").status_code, 200)

        events = snapshot["visible_events"]
        self.assertIn(
            "WINNER_DECIDED",
            {event["event_type"] for event in events},
        )
        role_events = [
            event
            for event in events
            if event["event_type"] == "ROLE_ASSIGNED"
        ]
        self.assertEqual(len(role_events), 9)

    def test_every_action_is_rejected_for_waiting_player_in_init(self) -> None:
        joined = self.client.post(
            f"/api/rooms/{self.room_id}/join",
            json={"nickname": "等待玩家"},
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        waiting_token = joined.json()["player_token"]

        for action in ACTION_PRIORITY:
            with self.subTest(action=action):
                response = self.client.post(
                    f"/api/rooms/{self.room_id}/actions",
                    headers={"X-Player-Token": waiting_token},
                    json={
                        "action": action,
                        "target_id": "p2",
                        "content": "越权尝试",
                        "choice": "none",
                    },
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    response.json()["detail"]["code"],
                    "ACTION_UNAVAILABLE",
                )

        snapshot_response = self.client.get(
            f"/api/rooms/{self.room_id}",
            headers={"X-Player-Token": waiting_token},
        )
        self.assertEqual(snapshot_response.status_code, 200)
        snapshot = snapshot_response.json()
        self.assertEqual(snapshot["phase"], "INIT")
        self.assertEqual(snapshot["available_actions"], [])


if __name__ == "__main__":
    unittest.main()
