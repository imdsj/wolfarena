"""Focused tests for the non-learning L1 rule policy."""

from __future__ import annotations

from unittest import TestCase

from backend.ai_growth import L1RulePolicy
from backend.game_engine import (
    EventType,
    NightResult,
    Phase,
    Role,
    Visibility,
    append_event,
)
from backend.schemas import ActionView
from backend.simulator import simulate_game
from tests.test_game_engine import controlled_game


class L1RulePolicyTests(TestCase):
    def test_speech_is_preferred_over_optional_self_destruct(self) -> None:
        policy = L1RulePolicy(seed=1)

        self.assertEqual(
            policy.choose_action(("self_destruct", "speech")),
            "speech",
        )

    def test_witch_uses_antidote_on_visible_knife_target(self) -> None:
        state = controlled_game(seed=501)
        witch = next(
            player for player in state.players if player.role is Role.WITCH
        )
        target = next(
            player
            for player in state.players
            if player.is_alive and player.player_id != witch.player_id
        )
        state.night_result = NightResult(wolf_target_id=target.player_id)
        view = ActionView(
            action="witch_action",
            label="女巫行动",
            target_ids=[
                player.player_id
                for player in state.players
                if player.is_alive
            ],
            choices=["none", "antidote", "poison"],
            allow_no_target=True,
        )
        policy = L1RulePolicy(seed=1)

        choice = policy.choose_choice(state, witch, view)
        target_id = policy.choose_target(
            state,
            witch,
            view,
            choice=choice,
        )

        self.assertEqual(choice, "antidote")
        self.assertEqual(target_id, target.player_id)

    def test_witch_without_antidote_chooses_none(self) -> None:
        state = controlled_game(seed=502)
        state.antidote_available = False
        witch = next(
            player for player in state.players if player.role is Role.WITCH
        )
        view = ActionView(
            action="witch_action",
            label="女巫行动",
            target_ids=[witch.player_id],
            choices=["none", "poison"],
            allow_no_target=True,
        )
        policy = L1RulePolicy(seed=1)

        choice = policy.choose_choice(state, witch, view)
        target_id = policy.choose_target(
            state,
            witch,
            view,
            choice=choice,
        )

        self.assertEqual(choice, "none")
        self.assertIsNone(target_id)

    def test_seer_prefers_unchecked_living_player(self) -> None:
        state = controlled_game(seed=503)
        seer = next(
            player for player in state.players if player.role is Role.SEER
        )
        targets = [
            player.player_id
            for player in state.players
            if player.is_alive and player.player_id != seer.player_id
        ]
        first_target, second_target = targets[:2]
        state.phase = Phase.NIGHT_SEER_CHECK
        append_event(
            state,
            EventType.SEER_CHECKED,
            actor_id=seer.player_id,
            target_id=first_target,
            visibility=Visibility.PLAYER,
            visible_to=(seer.player_id,),
            data={"result": "good"},
        )
        view = ActionView(
            action="seer_check",
            label="查验",
            target_ids=targets,
            requires_target=True,
        )

        target_id = L1RulePolicy(seed=1).choose_target(
            state,
            seer,
            view,
            choice=None,
        )

        self.assertEqual(target_id, second_target)

    def test_wolf_prefers_public_god_claim(self) -> None:
        state = controlled_game(seed=504)
        wolf = next(
            player for player in state.players if player.role is Role.WEREWOLF
        )
        claimant = next(
            player
            for player in state.players
            if player.role is not Role.WEREWOLF and player.is_alive
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=claimant.player_id,
            visibility=Visibility.PUBLIC,
            data={"content": "我是预言家"},
        )
        view = ActionView(
            action="wolf_kill",
            label="狼刀",
            target_ids=[
                player.player_id
                for player in state.players
                if player.is_alive
            ],
            allow_no_target=True,
        )

        target_id = L1RulePolicy(seed=1).choose_target(
            state,
            wolf,
            view,
            choice=None,
        )

        self.assertEqual(target_id, claimant.player_id)

    def test_l1_simulation_completes_with_only_legal_actions(self) -> None:
        summary, actions = simulate_game(
            seed=1000,
            policy_name="l1",
            max_action_steps=600,
            max_days=20,
        )

        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["terminal_phase"], "END")
        self.assertTrue(actions)
        self.assertTrue(
            all(
                action["action"] in action["legal_actions"]
                and action["ok"]
                for action in actions
            )
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
