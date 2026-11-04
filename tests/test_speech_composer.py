"""Tests for the optional LLM speech composer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from backend.ai_provider import DeepSeekSettings
from backend.game_engine import (
    EventType,
    Role,
    Visibility,
    append_event,
    create_game,
)
from backend.speech_composer import (
    compose_speech,
    llm_speech_enabled,
    private_context,
    public_history,
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
