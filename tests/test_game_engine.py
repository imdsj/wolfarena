"""Tests for the first game-engine milestone."""

from collections import Counter
from unittest import TestCase

from backend.game_engine import (
    EventType,
    GameState,
    NightResult,
    Phase,
    Role,
    Team,
    Visibility,
    check_winner,
    create_game,
    get_player,
    start_night,
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


class NightTransitionTests(TestCase):
    def test_start_night_advances_to_day_one_night(self) -> None:
        state = create_game(seed=11)

        returned_state = start_night(state)

        self.assertIs(returned_state, state)
        self.assertEqual(state.day, 1)
        self.assertEqual(state.phase, Phase.NIGHT)
        self.assertIsInstance(state.night_result, NightResult)
        self.assertEqual(state.events[-1].event_type, EventType.NIGHT_STARTED)
        self.assertEqual(state.events[-1].day, 1)

    def test_start_night_rejects_duplicate_night_transition(self) -> None:
        state = create_game(seed=12)
        start_night(state)

        with self.assertRaises(ValueError):
            start_night(state)

    def test_start_next_night_from_vote_phase(self) -> None:
        state = create_game(seed=13)
        state.phase = Phase.VOTE

        start_night(state)

        self.assertEqual(state.day, 1)
        self.assertEqual(state.phase, Phase.NIGHT)


class WinnerCheckTests(TestCase):
    def test_game_continues_at_initial_three_versus_six(self) -> None:
        state = create_game(seed=21)

        self.assertIsNone(check_winner(state))

    def test_good_wins_when_all_wolves_are_dead(self) -> None:
        state = create_game(seed=22)
        for player in state.players:
            if player.role is Role.WEREWOLF:
                player.is_alive = False

        self.assertEqual(check_winner(state), Team.GOOD)

    def test_wolves_win_when_their_count_reaches_good_count(self) -> None:
        state = create_game(seed=23)
        living_good = [
            player
            for player in state.players
            if player.team is Team.GOOD
        ]
        for player in living_good[3:]:
            player.is_alive = False

        self.assertEqual(check_winner(state), Team.WOLF)

    def test_good_wins_when_both_win_checks_are_true(self) -> None:
        state = create_game(seed=24)
        for player in state.players:
            player.is_alive = False

        self.assertEqual(check_winner(state), Team.GOOD)

    def test_dead_players_do_not_count_toward_winner(self) -> None:
        state = create_game(seed=25)
        wolves = [player for player in state.players if player.role is Role.WEREWOLF]
        wolves[0].is_alive = False

        self.assertIsNone(check_winner(state))
        wolves[1].is_alive = False
        self.assertIsNone(check_winner(state))
