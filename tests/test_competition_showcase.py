"""Regression tests for the strategy-growth and spectator prediction demo."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.ai_provider import DeepSeekSettings
from backend.game_engine import (
    DayResult,
    EventType,
    Phase,
    Role,
    Visibility,
    append_event,
    create_game,
    resolve_vote,
)
from backend.ai_growth import speech_content
from backend.logic_audit import admits_deception, audit, spoken_denial
from backend.rooms import InMemoryRoomRepository, ViewerAccess
from backend.strategy_learning import learn_one_game, learning_history
from backend.strategy_library import StrategyCard
from backend.tactic_policy import DirectivePolicy
from backend.win_probability import (
    baseline_timeline,
    predict_win_rate,
    public_transcript,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class NewSpeechAuditTests(TestCase):
    def test_public_self_counterclaim_is_a_hard_finding(self) -> None:
        state = create_game(seed=9101, human_count=0)
        speaker = state.players[2]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "我悍跳预言家：昨晚验1号，查杀。"},
        )
        findings = audit(state, state.players[0])
        self.assertIn("self_counterclaim", {item.kind for item in findings})
        self.assertTrue(admits_deception("我悍跳预言家"))
        self.assertFalse(admits_deception("我怀疑3号在悍跳预言家"))

    def test_speaker_cannot_deny_an_existing_public_speech(self) -> None:
        state = create_game(seed=9102, human_count=0)
        first = state.players[0]
        speaker = state.players[3]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=first.player_id,
            data={"content": "大家好"},
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "1号还没开口就被定死，太顺了。"},
        )
        findings = audit(state, state.players[1])
        self.assertIn("spoken_denial", {item.kind for item in findings})
        self.assertEqual(spoken_denial("1号发言前就被查杀", {1}), 1)
        self.assertIsNone(spoken_denial("1号发言前就被查杀", set()))

    def test_unspoken_accusation_and_unclaimed_check_prompt_are_caught(self) -> None:
        state = create_game(seed=9103, human_count=0)
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=state.players[5].player_id,
            data={"content": "我是村民，我看8号有点问题，先记着。"},
        )
        self.assertIn(
            "unfounded_unspoken_accusation",
            {item.kind for item in audit(state, state.players[0])},
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=state.players[3].player_id,
            data={"content": "我4号先听一轮，1号我再观察。"},
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=state.players[6].player_id,
            data={"content": "4号报查验吧，对不上就把票压过去。"},
        )
        self.assertIn(
            "unclaimed_check_prompt",
            {item.kind for item in audit(state, state.players[0])},
        )

    def test_template_does_not_accuse_a_player_who_has_not_spoken(self) -> None:
        state = create_game(seed=9104, human_count=0)
        state.phase = Phase.DAY_DISCUSSION
        state.day = 1
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=state.players[0].player_id,
            data={"content": "大家好。"},
        )
        actor = next(
            player
            for player in state.players[1:]
            if player.role is Role.VILLAGER
        )
        view = SimpleNamespace(action="speech", requires_content=True)
        text = speech_content(state, actor, view) or ""
        self.assertNotIn("有点问题", text)
        self.assertNotIn("最怀疑", text)
        self.assertNotIn("我怀疑", text)


class TerminalWinRateTests(TestCase):
    def test_last_wolf_vote_immediately_sets_good_to_one_hundred(self) -> None:
        state = create_game(seed=9105, human_count=0)
        last_wolf = next(
            player for player in state.players if player.role is Role.WEREWOLF
        )
        for player in state.players:
            if player.role is Role.WEREWOLF and player is not last_wolf:
                player.is_alive = False
        living_ids = [player.player_id for player in state.players if player.is_alive]
        state.phase = Phase.VOTE
        state.day_result = DayResult(
            speech_order=living_ids,
            votes={player_id: last_wolf.player_id for player_id in living_ids},
            votes_closed=True,
        )
        resolve_vote(state)
        self.assertEqual(state.phase, Phase.END)
        self.assertEqual(state.events[-1].event_type, EventType.WINNER_DECIDED)
        self.assertEqual(state.events[-1].data["winner"], "good")
        self.assertEqual(baseline_timeline(state)[-1]["good"], 1.0)


class WinProbabilityTests(TestCase):
    def _state(self):
        state = create_game(seed=9201, human_count=0)
        seer = next(player for player in state.players if player.role is Role.SEER)
        wolf = next(player for player in state.players if player.role is Role.WEREWOLF)
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=seer.player_id,
            data={"content": f"我是预言家，我验了{wolf.seat}号是狼。"},
        )
        append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={"content": "秘密刀口和真实队友"},
        )
        append_event(
            state,
            EventType.SEER_CHECKED,
            actor_id=seer.player_id,
            target_id=wolf.player_id,
            visibility=Visibility.PLAYER,
            visible_to=(seer.player_id,),
            data={"result": "wolf"},
        )
        return state, seer, wolf

    @staticmethod
    def _speech_seq(state) -> int:
        return next(
            event.event_seq
            for event in state.events
            if event.event_type is EventType.PUBLIC_SPEECH
        )

    def test_public_transcript_never_contains_private_roles_or_night_data(self) -> None:
        state, _, _ = self._state()
        transcript = public_transcript(state, self._speech_seq(state))
        self.assertIn("是狼", transcript)
        self.assertNotIn("秘密刀口", transcript)
        self.assertNotIn("SEER_CHECKED", transcript)
        self.assertNotIn("werewolf", transcript)

    def test_baseline_is_deterministic_and_moves_on_public_evidence(self) -> None:
        state, _, _ = self._state()
        first = baseline_timeline(state)
        self.assertEqual(first, baseline_timeline(state))
        self.assertGreater(first[0]["good"], 0.5)

    def test_deepseek_prediction_is_labelled_and_blended(self) -> None:
        state, _, _ = self._state()
        with patch(
            "backend.win_probability._deepseek_estimate",
            return_value={
                "good": 0.8,
                "reason": "公开查杀提供归票依据",
                "drivers": ["查杀声明"],
            },
        ):
            result = predict_win_rate(
                state,
                self._speech_seq(state),
                settings=DeepSeekSettings(api_key="test-key"),
            )
        self.assertEqual(result["source"], "deepseek_hybrid")
        self.assertEqual(result["llm_good"], 0.8)
        self.assertAlmostEqual(
            result["good"],
            round(0.35 * result["baseline_good"] + 0.65 * 0.8, 4),
        )

    def test_failed_model_is_not_mislabelled(self) -> None:
        state, _, _ = self._state()
        result = predict_win_rate(
            state,
            self._speech_seq(state),
            settings=DeepSeekSettings(api_key=None),
        )
        self.assertEqual(result["source"], "statistical_fallback")
        self.assertIsNone(result["llm_good"])

    def test_spectator_gets_curve_and_prediction_is_cached(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=9202,
            human_count=1,
            max_humans=3,
            nickname="观战测试",
        )
        room = repository._rooms[created.room_id]
        state, _, _ = self._state()
        room.state = state
        access = ViewerAccess(room_id=room.room_id, kind="spectator")
        snapshot = repository.snapshot_for_access(room, access)
        self.assertEqual(len(snapshot.win_rate_timeline), 1)
        with patch(
            "backend.rooms.predict_win_rate",
            side_effect=lambda _state, _seq: {
                "event_seq": 0,
                "source": "statistical_fallback",
            },
        ) as predictor:
            first = repository.win_rate_prediction(access, 0)
            second = repository.win_rate_prediction(access, 0)
        self.assertEqual(first, second)
        predictor.assert_called_once()


class TacticExecutionTraceTests(TestCase):
    def test_applied_directive_is_named_in_the_decision_trace(self) -> None:
        state = create_game(seed=9250, human_count=0)
        state.phase = Phase.VOTE
        speaker = state.players[0]
        target = state.players[4]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": f"我觉得{target.seat}号是狼，今天票他。"},
        )
        card = StrategyCard(
            strategy_id="cand.test.applied-directive",
            title="测试归票战术",
            role="villager",
            phase="VOTE",
            action="vote",
            trigger="多人怀疑",
            recommendation="跟最高嫌疑",
            rationale="测试",
            risk="误判",
            source_type="agent_observation",
            source="测试",
            status="validated",
            created_by="ai",
            created_at="2026-01-01T00:00:00+00:00",
            directive="vote_most_accused",
        )
        actor = next(
            player for player in state.players if player.role is Role.VILLAGER
        )
        policy = DirectivePolicy(seed=9250, cards=(card,))
        view = type(
            "View",
            (),
            {
                "action": "vote",
                "target_ids": [p.player_id for p in state.players if p.is_alive],
            },
        )()
        self.assertEqual(
            policy.applied_tactic_ids(state, actor, view),
            ["cand.test.applied-directive"],
        )


class StrategyLearningTests(TestCase):
    def test_one_real_game_creates_candidate_and_replay_receipt(self) -> None:
        root = PROJECT_ROOT / "training_runs" / f"test-learning-{uuid4().hex}"
        strategy_root = root / "library"
        learning_root = root / "receipts"
        result = learn_one_game(
            9301,
            strategy_root=strategy_root,
            learning_root=learning_root,
            settings=DeepSeekSettings(api_key=None),
        )
        self.assertEqual(result["receipt"]["seed"], 9301)
        self.assertGreater(result["receipt"]["action_steps"], 0)
        self.assertEqual(result["receipt"]["generation_source"], "rule_fallback")
        self.assertEqual(result["card"]["status"], "candidate")
        self.assertIn("generation:rule_fallback", result["card"]["tags"])
        self.assertTrue((learning_root / "seed-9301" / "actions.jsonl").is_file())
        history = learning_history(learning_root=learning_root)
        self.assertEqual(history[0]["strategy_id"], result["card"]["strategy_id"])


class ShowcaseApiTests(TestCase):
    def test_learning_endpoint_uses_the_requested_seed(self) -> None:
        client = TestClient(create_app(InMemoryRoomRepository()))
        with patch(
            "backend.api.learn_one_game",
            return_value={"receipt": {"seed": 9401}, "card": {}, "evidence_path": "x"},
        ) as learn:
            response = client.post("/api/strategy/learn", json={"seed": 9401})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(learn.call_args.args[0], 9401)

    def test_win_rate_endpoint_requires_spectator_password(self) -> None:
        repository = InMemoryRoomRepository()
        client = TestClient(create_app(repository))
        created = client.post(
            "/api/rooms",
            json={"seed": 9402, "human_count": 1, "nickname": "胜率测试"},
        ).json()
        state, _, _ = WinProbabilityTests()._state()
        repository._rooms[created["room_id"]].state = state
        seq = WinProbabilityTests._speech_seq(state)
        with patch(
            "backend.win_probability.DeepSeekSettings.from_environment",
            return_value=DeepSeekSettings(api_key=None),
        ):
            response = client.post(
                f"/api/rooms/{created['room_id']}/win-rate/{seq}",
                headers={"X-Spectator-Password": created["spectator_password"]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["source"], "statistical_fallback")
        rejected = client.post(f"/api/rooms/{created['room_id']}/win-rate/{seq}")
        self.assertEqual(rejected.status_code, 401)


if __name__ == "__main__":
    import unittest

    unittest.main()
