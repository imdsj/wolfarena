"""Tests for the optional LLM speech composer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from backend.ai_provider import DeepSeekSettings
from backend.game_engine import (
    DayResult,
    EventType,
    Phase,
    Role,
    Visibility,
    append_event,
    create_game,
)
from backend.speech_composer import (
    speaking_order,
    compose_speech,
    llm_speech_enabled,
    private_context,
    public_history,
    tactic_query,
    tactics_context,
)


class SpeechComposerTests(TestCase):
    def test_flag_defaults_off(self) -> None:
        self.assertFalse(llm_speech_enabled())

    def test_compose_returns_none_without_api_key(self) -> None:
        state = create_game(seed=5, human_count=0)
        actor = next(
            player for player in state.players if player.role is Role.VILLAGER
        )
        view = SimpleNamespace(requires_content=True, action="speech")
        self.assertIsNone(
            compose_speech(
                state=state,
                actor=actor,
                view=view,
                settings=DeepSeekSettings(api_key=None),
            )
        )

    def test_public_history_excludes_wolf_speech(self) -> None:
        state = create_game(seed=5, human_count=0)
        villager = next(
            player for player in state.players if player.role is Role.VILLAGER
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id="p1",
            visibility=Visibility.PUBLIC,
            data={"content": "公开"},
        )
        wolf = next(
            player for player in state.players if player.role is Role.WEREWOLF
        )
        append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={"content": "狼聊"},
        )
        history = public_history(state, villager)
        self.assertIn("1 号：公开", history)
        self.assertNotIn("狼聊", " ".join(history))

    def test_seer_private_context_uses_real_check_history(self) -> None:
        state = create_game(seed=5, human_count=0)
        seer = next(
            player for player in state.players if player.role is Role.SEER
        )
        wolf = next(
            player for player in state.players if player.role is Role.WEREWOLF
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
        context = private_context(state, seer)
        self.assertIn(f"{wolf.seat} 号是狼人", context)
        self.assertIn("不得编造", context)

    def test_wolf_private_context_lists_teammates(self) -> None:
        state = create_game(seed=5, human_count=0)
        wolves = [
            player for player in state.players if player.role is Role.WEREWOLF
        ]
        context = private_context(state, wolves[0])
        self.assertIn(f"{wolves[1].seat} 号", context)
        self.assertIn("伪装", context)

    def test_tactics_context_grounds_seer_in_night_check(self) -> None:
        state = create_game(seed=5, human_count=0)
        seer = next(
            player for player in state.players if player.role is Role.SEER
        )
        state.phase = Phase.NIGHT_SEER_CHECK
        context = tactics_context(state, seer)
        self.assertIn("战术库参考", context)
        self.assertIn("预言家", context)
        self.assertIn("来源：", context)

    def test_tactic_query_uses_public_board_but_not_wolf_chat(self) -> None:
        state = create_game(seed=330, human_count=0)
        villager = next(
            player for player in state.players if player.role is Role.VILLAGER
        )
        wolf = next(
            player for player in state.players if player.role is Role.WEREWOLF
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id="p1",
            visibility=Visibility.PUBLIC,
            data={"content": "我关注连续同票"},
        )
        append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={"content": "狼队秘密刀口"},
        )
        for day, target_id in ((1, "p3"), (2, "p5")):
            state.day = day
            append_event(
                state,
                EventType.VOTE_RESULT,
                visibility=Visibility.PUBLIC,
                data={
                    "votes": {
                        "p1": target_id,
                        "p2": target_id,
                        "p3": "p1",
                    }
                },
            )

        query = tactic_query(state, villager)

        self.assertIn("我关注连续同票", query)
        self.assertIn("1号与2号连续2天同票", query)
        self.assertNotIn("狼队秘密刀口", query)

    def test_tactics_context_retrieves_vote_tactic_for_current_board(self) -> None:
        state = create_game(seed=330, human_count=0)
        state.phase = Phase.DAY_DISCUSSION
        villager = next(
            player for player in state.players if player.role is Role.VILLAGER
        )
        for day, target_id in ((1, "p3"), (2, "p5")):
            state.day = day
            append_event(
                state,
                EventType.VOTE_RESULT,
                visibility=Visibility.PUBLIC,
                data={
                    "votes": {
                        "p1": target_id,
                        "p2": target_id,
                        "p3": "p1",
                    }
                },
            )

        context = tactics_context(state, villager)

        self.assertIn("good.read-vote-blocs", context)
        self.assertIn("已经出现至少两天的公开票型", context)
        self.assertIn("WolfArena 2026-11-09 复盘", context)

    def test_speaking_order_ignores_night_death_speaker(self) -> None:
        state = create_game(seed=5, human_count=0)
        state.day = 1
        dead = state.players[2]
        dead.is_alive = False
        state.day_result = DayResult(
            speech_order=[
                p.player_id for p in state.players if p.player_id != dead.player_id
            ][:5]
        )
        self.assertEqual(speaking_order(state, dead), "")


class SpeechFallbackTests(TestCase):
    def test_llm_failure_falls_back_to_template(self) -> None:
        from backend.ai_controller import AIController
        from backend.ai_growth import L1RulePolicy

        state = create_game(seed=5, human_count=0)
        state.phase = Phase.DAY_DISCUSSION
        state.day = 1
        actor = state.players[3]
        view = SimpleNamespace(action="speech", requires_content=True)
        with patch(
            "backend.ai_controller.llm_speech_enabled",
            return_value=True,
        ), patch(
            "backend.ai_controller.compose_speech_with_tools",
            return_value=(None, [{"name": "audit_logic"}]),
        ):
            text, tool_calls = AIController._speech_content_with_tools(
                state,
                actor,
                view,
                L1RulePolicy(seed=5),
            )
        # Empty LLM output must never reach the action layer: fall back to the
        # deterministic template so later speakers are not stalled.
        self.assertIsNotNone(text)
        self.assertTrue(text.strip())
        self.assertEqual(tool_calls, [{"name": "audit_logic"}])
