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
