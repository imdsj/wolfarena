"""Tests for the first game-engine milestone."""

from collections import Counter
from unittest import TestCase

from backend.game_engine import (
    EventType,
    GameState,
    Phase,
    Role,
    Team,
    Visibility,
    create_game,
    get_player,
)


class GameCreationTests(TestCase):
    def test_create_game_returns_initial_state(self) -> None:
        state = create_game(seed=20261022)

        self.assertIsInstance(state, GameState)
        self.assertEqual(state.phase, Phase.INIT)
        self.assertEqual(state.day, 0)
        self.assertIsNone(state.night_result)
        self.assertEqual(state.seed, 20261022)

    def test_game_has_nine_living_players_with_unique_ids(self) -> None:
        state = create_game(seed=1)
        player_ids = [player.player_id for player in state.players]

        self.assertEqual(len(state.players), 9)
        self.assertEqual(len(set(player_ids)), 9)
        self.assertTrue(all(player.is_alive for player in state.players))
        self.assertEqual([player.seat for player in state.players], list(range(1, 10)))

    def test_role_counts_are_fixed(self) -> None:
        state = create_game(seed=1)

        self.assertEqual(
            state.role_counts(),
            Counter(
                {
                    Role.WEREWOLF: 3,
                    Role.VILLAGER: 3,
                    Role.SEER: 1,
                    Role.WITCH: 1,
                    Role.HUNTER: 1,
                }
            ),
        )
        self.assertEqual(
            Counter(player.team for player in state.players),
            Counter({Team.GOOD: 6, Team.WOLF: 3}),
        )

    def test_same_seed_repeats_the_same_role_assignment(self) -> None:
        first = create_game(seed=987654)
        second = create_game(seed=987654)

        first_assignment = {
            player.player_id: player.role for player in first.players
        }
        second_assignment = {
            player.player_id: player.role for player in second.players
        }
        self.assertEqual(first_assignment, second_assignment)

    def test_100_games_always_have_the_fixed_roster(self) -> None:
        expected = Counter(
            {
                Role.WEREWOLF: 3,
                Role.VILLAGER: 3,
                Role.SEER: 1,
                Role.WITCH: 1,
                Role.HUNTER: 1,
            }
        )

        for seed in range(100):
            with self.subTest(seed=seed):
                state = create_game(seed=seed)
                self.assertEqual(len(state.players), 9)
                self.assertEqual(state.role_counts(), expected)

    def test_human_and_ai_flags_follow_human_count(self) -> None:
        state = create_game(seed=42, human_count=3)

        self.assertEqual(sum(player.is_human for player in state.players), 3)
        self.assertTrue(all(player.is_human for player in state.players[:3]))
        self.assertTrue(all(not player.is_human for player in state.players[3:]))

    def test_custom_names_and_player_lookup_work(self) -> None:
        names = [f"选手{number}" for number in range(1, 10)]
        state = create_game(seed=8, player_names=names)

        self.assertEqual(get_player(state, "p4").name, "选手4")
        self.assertEqual(get_player(state, "选手4").player_id, "p4")
        with self.assertRaises(KeyError):
            get_player(state, "不存在")

    def test_role_assignment_events_are_private_and_complete(self) -> None:
        state = create_game(seed=3)
        role_events = [
            event
            for event in state.events
            if event.event_type is EventType.ROLE_ASSIGNED
        ]

        self.assertEqual(len(state.events), 10)
        self.assertEqual(len(role_events), 9)
        self.assertTrue(
            all(event.visibility is Visibility.PLAYER for event in role_events)
        )
        self.assertTrue(all(len(event.visible_to) == 1 for event in role_events))
        self.assertEqual(
            {event.target_id for event in role_events},
            {player.player_id for player in state.players},
        )

    def test_invalid_inputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_game(seed=1, human_count=10)
        with self.assertRaises(ValueError):
            create_game(seed=1, player_names=["人数不足"])
        with self.assertRaises(ValueError):
            create_game(seed=1, player_names=["同名"] * 9)
        with self.assertRaises(TypeError):
            create_game(seed="1")  # type: ignore[arg-type]
