"""Tests for the first game-engine milestone."""

from collections import Counter
from unittest import TestCase

from backend.game_engine import (
    Event,
    EventType,
    GameState,
    NightResult,
    PHASE_ORDER,
    Phase,
    Role,
    SPECTATOR_VIEW,
    Team,
    Visibility,
    append_event,
    check_winner,
    create_game,
    get_player,
    get_visible_events,
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

    def test_human_count_above_three_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_game(seed=1, human_count=4)

    def test_zero_human_count_is_allowed_for_ai_only(self) -> None:
        state = create_game(seed=1, human_count=0)

        self.assertEqual(sum(player.is_human for player in state.players), 0)
        self.assertTrue(all(not player.is_human for player in state.players))

    def test_custom_names_and_player_lookup_work(self) -> None:
        names = [f"选手{number}" for number in range(1, 10)]
        state = create_game(seed=8, player_names=names)

        self.assertEqual(get_player(state, "p4").name, "选手4")
        self.assertEqual(get_player(state, "选手4").player_id, "p4")
        with self.assertRaises(KeyError):
            get_player(state, "不存在")

    def test_role_assignment_events_follow_team_visibility(self) -> None:
        state = create_game(seed=3)
        role_events = [
            event
            for event in state.events
            if event.event_type is EventType.ROLE_ASSIGNED
        ]
        role_by_player = {
            player.player_id: player.role for player in state.players
        }

        self.assertEqual(len(state.events), 10)
        self.assertEqual(len(role_events), 9)
        self.assertTrue(
            all(
                event.visibility is Visibility.WOLVES
                if role_by_player[event.target_id] is Role.WEREWOLF
                else event.visibility is Visibility.PLAYER
                for event in role_events
            )
        )
        self.assertTrue(
            all(
                len(event.visible_to) == 0
                if role_by_player[event.target_id] is Role.WEREWOLF
                else event.visible_to == (event.target_id,)
                for event in role_events
            )
        )
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
        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
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
        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)


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


class NightTransitionEdgeTests(TestCase):
    """Boundary cases for entering the night phase (GAME-003, DESTRUCT-008)."""

    def test_start_night_from_self_destruct_phase(self) -> None:
        state = create_game(seed=14)
        state.phase = Phase.SELF_DESTRUCT

        start_night(state)

        self.assertEqual(state.day, 1)
        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)

    def test_start_night_rejects_day_discussion_phase(self) -> None:
        state = create_game(seed=15)
        state.phase = Phase.DAY_DISCUSSION

        with self.assertRaises(ValueError):
            start_night(state)

        self.assertEqual(state.phase, Phase.DAY_DISCUSSION)
        self.assertEqual(state.day, 0)

    def test_start_night_rejects_finished_game(self) -> None:
        state = create_game(seed=16)
        state.phase = Phase.END

        with self.assertRaises(ValueError):
            start_night(state)

        self.assertEqual(state.phase, Phase.END)


class PhaseAndEventModelTests(TestCase):
    def test_phase_order_and_values_are_stable_and_unique(self) -> None:
        expected_phases = (
            Phase.INIT,
            Phase.NIGHT_WOLF_DISCUSSION_R1,
            Phase.NIGHT_WOLF_DISCUSSION_R2,
            Phase.NIGHT_WOLF_KILL,
            Phase.NIGHT_SEER_CHECK,
            Phase.NIGHT_WITCH_ACTION,
            Phase.NIGHT_RESOLUTION,
            Phase.NIGHT_HUNTER_SHOT,
            Phase.DAY_ANNOUNCEMENT,
            Phase.DAY_LAST_WORDS,
            Phase.DAY_DISCUSSION,
            Phase.SELF_DESTRUCT,
            Phase.VOTE,
            Phase.DAY_HUNTER_SHOT,
            Phase.END,
        )

        self.assertEqual(PHASE_ORDER, expected_phases)
        self.assertEqual(tuple(Phase), expected_phases)
        self.assertEqual(len(Phase), len({phase.value for phase in Phase}))

    def test_required_event_types_are_stable_and_unique(self) -> None:
        required_event_values = {
            "GAME_CREATED",
            "ROLE_ASSIGNED",
            "WOLF_CAPTAIN_ELECTED",
            "WOLF_SPEECH",
            "WOLF_KILL_SELECTED",
            "SEER_CHECKED",
            "WITCH_USED_ANTIDOTE",
            "WITCH_USED_POISON",
            "PLAYER_DIED",
            "HUNTER_SHOT",
            "SELF_DESTRUCTED",
            "VOTE_CAST",
            "WINNER_DECIDED",
        }

        self.assertTrue(required_event_values <= {item.value for item in EventType})
        self.assertEqual(
            len(EventType),
            len({event_type.value for event_type in EventType}),
        )

    def test_event_sequence_is_contiguous(self) -> None:
        state = create_game(seed=31)
        start_night(state)
        append_event(
            state,
            EventType.WOLF_SPEECH,
            visibility=Visibility.WOLVES,
            data={"round": 1},
        )

        event_sequences = [event.event_seq for event in state.events]
        self.assertEqual(event_sequences, list(range(len(state.events))))
        self.assertIsInstance(state.events[-1], Event)

    def test_every_event_keeps_required_fields(self) -> None:
        state = create_game(seed=32)
        event = state.events[0]
        required_fields = {
            "event_seq",
            "event_type",
            "day",
            "phase",
            "actor_id",
            "target_id",
            "visibility",
            "visible_to",
            "data",
        }

        self.assertEqual(set(event.__dataclass_fields__), required_fields)


class EventVisibilityTests(TestCase):
    def test_player_wolf_and_spectator_views_are_different(self) -> None:
        state = create_game(seed=33)
        start_night(state)
        player = next(player for player in state.players if player.role is Role.SEER)
        wolf = next(player for player in state.players if player.role is Role.WEREWOLF)

        private_event = append_event(
            state,
            EventType.SEER_CHECKED,
            actor_id=player.player_id,
            target_id=wolf.player_id,
            visibility=Visibility.PLAYER,
            visible_to=(player.player_id,),
            data={"result": "wolf"},
        )
        wolf_event = append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={"round": 1},
        )
        god_event = append_event(
            state,
            EventType.WOLF_KILL_SELECTED,
            actor_id=wolf.player_id,
            target_id=player.player_id,
            visibility=Visibility.GOD,
        )

        player_event_ids = {
            event.event_seq for event in get_visible_events(state, player)
        }
        wolf_event_ids = {
            event.event_seq for event in get_visible_events(state, wolf.player_id)
        }
        spectator_event_ids = {
            event.event_seq for event in get_visible_events(state, SPECTATOR_VIEW)
        }

        self.assertIn(private_event.event_seq, player_event_ids)
        self.assertNotIn(wolf_event.event_seq, player_event_ids)
        self.assertNotIn(god_event.event_seq, player_event_ids)

        self.assertIn(wolf_event.event_seq, wolf_event_ids)
        self.assertNotIn(private_event.event_seq, wolf_event_ids)
        self.assertNotIn(god_event.event_seq, wolf_event_ids)

        self.assertEqual(
            spectator_event_ids,
            {event.event_seq for event in state.events},
        )
        self.assertNotEqual(player_event_ids, wolf_event_ids)
        self.assertNotEqual(player_event_ids, spectator_event_ids)

    def test_dead_wolf_loses_team_view_until_game_end(self) -> None:
        state = create_game(seed=34)
        start_night(state)
        wolf = next(player for player in state.players if player.role is Role.WEREWOLF)
        wolf_event = append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={"round": 1},
        )

        wolf.is_alive = False
        hidden_event_ids = {
            event.event_seq for event in get_visible_events(state, wolf)
        }
        self.assertNotIn(wolf_event.event_seq, hidden_event_ids)

        state.phase = Phase.END
        revealed_event_ids = {
            event.event_seq for event in get_visible_events(state, wolf)
        }
        self.assertIn(wolf_event.event_seq, revealed_event_ids)
