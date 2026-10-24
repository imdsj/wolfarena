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
    elect_wolf_captain,
    get_player,
    get_witch_kill_target,
    get_visible_events,
    record_wolf_speech,
    resolve_night,
    select_wolf_kill,
    start_night,
    submit_seer_check,
    submit_witch_action,
)


def controlled_game(seed: int = 101):
    """Create a deterministic roster for focused night-action tests."""

    state = create_game(seed=seed, human_count=0)
    roles = (
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.WEREWOLF,
        Role.VILLAGER,
        Role.VILLAGER,
        Role.VILLAGER,
        Role.SEER,
        Role.WITCH,
        Role.HUNTER,
    )
    for player, role in zip(state.players, roles):
        player.role = role
    return state


def player_with_role(state: GameState, role: Role):
    return next(player for player in state.players if player.role is role)


def advance_to_wolf_kill(state: GameState) -> list:
    elect_wolf_captain(state)
    start_night(state)
    living_wolves = sorted(
        (
            player
            for player in state.players
            if player.role is Role.WEREWOLF and player.is_alive
        ),
        key=lambda player: player.seat,
    )
    for player in living_wolves:
        record_wolf_speech(state, player.player_id, 1, f"第一轮-{player.seat}")
    for player in living_wolves:
        record_wolf_speech(state, player.player_id, 2, f"第二轮-{player.seat}")
    return living_wolves


def advance_to_witch(
    state: GameState,
    wolf_target_id: str,
) -> None:
    advance_to_wolf_kill(state)
    select_wolf_kill(state, state.wolf_captain_id, wolf_target_id)
    seer = player_with_role(state, Role.SEER)
    target = next(
        player for player in state.players if player.player_id != seer.player_id
    )
    submit_seer_check(state, seer.player_id, target.player_id)


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
            "VOTE_CLOSED",
            "VOTE_RESULT",
            "BANISHMENT_LAST_WORDS_STARTED",
            "PUBLIC_SPEECH",
            "PUBLIC_SPEECH_TIMEOUT",
            "LAST_WORDS",
            "LAST_WORDS_TIMEOUT",
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

    def test_dead_wolf_keeps_own_role_but_not_teammate_roles(self) -> None:
        state = create_game(seed=35)
        wolves = [
            player
            for player in state.players
            if player.role is Role.WEREWOLF
        ]
        viewer = wolves[0]
        viewer.is_alive = False

        visible_role_targets = {
            event.target_id
            for event in get_visible_events(state, viewer)
            if event.event_type is EventType.ROLE_ASSIGNED
        }

        self.assertIn(viewer.player_id, visible_role_targets)
        self.assertNotIn(wolves[1].player_id, visible_role_targets)
        self.assertNotIn(wolves[2].player_id, visible_role_targets)


class WolfCaptainTests(TestCase):
    def test_all_ai_captain_is_reproducible(self) -> None:
        first = controlled_game(seed=201)
        second = controlled_game(seed=201)

        elect_wolf_captain(first)
        elect_wolf_captain(second)

        self.assertEqual(first.wolf_captain_id, second.wolf_captain_id)
        event = next(
            event
            for event in first.events
            if event.event_type is EventType.WOLF_CAPTAIN_ELECTED
        )
        self.assertEqual(event.visibility, Visibility.WOLVES)
        self.assertEqual(event.data["selection"], "seed_random")

    def test_single_human_wolf_becomes_captain_automatically(self) -> None:
        state = controlled_game(seed=202)
        human_wolf = player_with_role(state, Role.WEREWOLF)
        human_wolf.is_human = True

        elect_wolf_captain(state)

        self.assertEqual(state.wolf_captain_id, human_wolf.player_id)
        captain_event = next(
            event
            for event in state.events
            if event.event_type is EventType.WOLF_CAPTAIN_ELECTED
        )
        self.assertEqual(captain_event.data["selection"], "only_human")

    def test_multiple_human_wolves_can_select_captain_manually(self) -> None:
        state = controlled_game(seed=203)
        wolves = sorted(
            (
                player
                for player in state.players
                if player.role is Role.WEREWOLF
            ),
            key=lambda player: player.seat,
        )
        wolves[0].is_human = True
        wolves[1].is_human = True

        elect_wolf_captain(state, captain_id=wolves[1].player_id)

        self.assertEqual(state.wolf_captain_id, wolves[1].player_id)
        captain_event = next(
            event
            for event in state.events
            if event.event_type is EventType.WOLF_CAPTAIN_ELECTED
        )
        self.assertEqual(captain_event.data["selection"], "manual")

    def test_dead_or_non_wolf_candidate_is_rejected(self) -> None:
        state = controlled_game(seed=204)
        wolf = player_with_role(state, Role.WEREWOLF)
        wolf.is_alive = False
        villager = player_with_role(state, Role.VILLAGER)

        with self.assertRaises(ValueError):
            elect_wolf_captain(state, captain_id=wolf.player_id)
        with self.assertRaises(ValueError):
            elect_wolf_captain(state, captain_id=villager.player_id)


class WolfSpeechTests(TestCase):
    def test_two_ordered_rounds_advance_to_wolf_kill(self) -> None:
        state = controlled_game(seed=211)
        living_wolves = advance_to_wolf_kill(state)

        self.assertEqual(state.phase, Phase.NIGHT_WOLF_KILL)
        speech_events = [
            event
            for event in state.events
            if event.event_type is EventType.WOLF_SPEECH
        ]
        self.assertEqual(len(speech_events), len(living_wolves) * 2)
        self.assertTrue(
            all(event.visibility is Visibility.WOLVES for event in speech_events)
        )

    def test_wrong_role_round_phase_and_order_are_rejected(self) -> None:
        state = controlled_game(seed=212)
        elect_wolf_captain(state)
        start_night(state)
        wolves = sorted(
            (
                player
                for player in state.players
                if player.role is Role.WEREWOLF
            ),
            key=lambda player: player.seat,
        )
        villager = player_with_role(state, Role.VILLAGER)

        with self.assertRaises(ValueError):
            record_wolf_speech(state, villager.player_id, 1, "非狼人")
        with self.assertRaises(ValueError):
            record_wolf_speech(state, wolves[1].player_id, 1, "跳过座次")
        with self.assertRaises(ValueError):
            record_wolf_speech(state, wolves[0].player_id, 2, "错误轮次")
        with self.assertRaises(ValueError):
            record_wolf_speech(state, wolves[0].player_id, 0, "非法轮次")


class WolfKillTests(TestCase):
    def test_only_captain_can_submit_one_kill(self) -> None:
        state = controlled_game(seed=221)
        wolves = advance_to_wolf_kill(state)
        captain = get_player(state, state.wolf_captain_id)
        other_wolf = next(player for player in wolves if player is not captain)
        target = player_with_role(state, Role.VILLAGER)

        with self.assertRaises(ValueError):
            select_wolf_kill(state, other_wolf.player_id, target.player_id)

        select_wolf_kill(state, captain.player_id, target.player_id)
        self.assertEqual(state.phase, Phase.NIGHT_SEER_CHECK)
        self.assertTrue(state.night_result.wolf_kill_submitted)
        self.assertEqual(state.night_result.wolf_target_id, target.player_id)

        with self.assertRaises(ValueError):
            select_wolf_kill(state, captain.player_id, None)

    def test_empty_kill_and_self_kill_are_legal(self) -> None:
        empty_state = controlled_game(seed=222)
        advance_to_wolf_kill(empty_state)
        select_wolf_kill(empty_state, empty_state.wolf_captain_id, None)
        self.assertEqual(empty_state.night_result.wolf_kill_type, "empty")
        self.assertIsNone(empty_state.night_result.wolf_target_id)

        self_kill_state = controlled_game(seed=223)
        advance_to_wolf_kill(self_kill_state)
        select_wolf_kill(
            self_kill_state,
            self_kill_state.wolf_captain_id,
            self_kill_state.wolf_captain_id,
        )
        self.assertEqual(self_kill_state.night_result.wolf_kill_type, "self")
        self.assertEqual(
            self_kill_state.night_result.wolf_target_id,
            self_kill_state.wolf_captain_id,
        )

    def test_dead_target_is_rejected(self) -> None:
        state = controlled_game(seed=224)
        advance_to_wolf_kill(state)
        target = player_with_role(state, Role.VILLAGER)
        target.is_alive = False

        with self.assertRaises(ValueError):
            select_wolf_kill(state, state.wolf_captain_id, target.player_id)


class SeerCheckTests(TestCase):
    def test_seer_result_is_private_and_correct(self) -> None:
        state = controlled_game(seed=231)
        wolves = advance_to_wolf_kill(state)
        select_wolf_kill(state, state.wolf_captain_id, None)
        seer = player_with_role(state, Role.SEER)
        target_wolf = wolves[0]

        result = submit_seer_check(state, seer.player_id, target_wolf.player_id)

        self.assertEqual(result, Team.WOLF)
        self.assertEqual(state.night_result.seer_result, "wolf")
        self.assertEqual(state.phase, Phase.NIGHT_WITCH_ACTION)
        seer_events = [
            event
            for event in get_visible_events(state, seer)
            if event.event_type is EventType.SEER_CHECKED
        ]
        wolf_events = [
            event
            for event in get_visible_events(state, target_wolf)
            if event.event_type is EventType.SEER_CHECKED
        ]
        self.assertEqual(len(seer_events), 1)
        self.assertEqual(wolf_events, [])

    def test_invalid_seer_targets_and_actors_are_rejected(self) -> None:
        state = controlled_game(seed=232)
        advance_to_wolf_kill(state)
        select_wolf_kill(state, state.wolf_captain_id, None)
        seer = player_with_role(state, Role.SEER)
        villager = player_with_role(state, Role.VILLAGER)

        with self.assertRaises(ValueError):
            submit_seer_check(state, villager.player_id, seer.player_id)
        with self.assertRaises(ValueError):
            submit_seer_check(state, seer.player_id, seer.player_id)

        villager.is_alive = False
        with self.assertRaises(ValueError):
            submit_seer_check(state, seer.player_id, villager.player_id)


class WitchActionTests(TestCase):
    def test_antidote_can_save_witch_and_consumes_once(self) -> None:
        state = controlled_game(seed=241)
        witch = player_with_role(state, Role.WITCH)
        advance_to_witch(state, witch.player_id)

        self.assertEqual(
            get_witch_kill_target(state, witch.player_id),
            witch.player_id,
        )
        submit_witch_action(
            state,
            witch.player_id,
            "antidote",
            witch.player_id,
        )

        self.assertFalse(state.antidote_available)
        self.assertEqual(state.night_result.antidote_target_id, witch.player_id)
        self.assertEqual(state.phase, Phase.NIGHT_RESOLUTION)
        resolve_night(state)
        self.assertTrue(witch.is_alive)
        self.assertEqual(state.phase, Phase.DAY_ANNOUNCEMENT)

    def test_poison_can_target_any_living_player(self) -> None:
        state = controlled_game(seed=242)
        hunter = player_with_role(state, Role.HUNTER)
        witch = player_with_role(state, Role.WITCH)
        villager = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, villager.player_id)

        submit_witch_action(state, witch.player_id, "poison", hunter.player_id)

        self.assertFalse(state.poison_available)
        self.assertEqual(state.night_result.poison_target_id, hunter.player_id)

    def test_none_and_used_potions_follow_limits(self) -> None:
        none_state = controlled_game(seed=243)
        witch = player_with_role(none_state, Role.WITCH)
        target = player_with_role(none_state, Role.VILLAGER)
        advance_to_witch(none_state, target.player_id)

        submit_witch_action(none_state, witch.player_id, "none")
        self.assertTrue(none_state.night_result.witch_action_submitted)
        self.assertTrue(none_state.antidote_available)
        self.assertTrue(none_state.poison_available)
        self.assertEqual(none_state.phase, Phase.NIGHT_RESOLUTION)

        exhausted_state = controlled_game(seed=244)
        witch = player_with_role(exhausted_state, Role.WITCH)
        target = player_with_role(exhausted_state, Role.VILLAGER)
        advance_to_witch(exhausted_state, target.player_id)
        exhausted_state.antidote_available = False
        with self.assertRaises(ValueError):
            submit_witch_action(
                exhausted_state,
                witch.player_id,
                "antidote",
                witch.player_id,
            )

    def test_witch_cannot_see_kill_target_without_antidote(self) -> None:
        state = controlled_game(seed=247)
        state.antidote_available = False
        witch = player_with_role(state, Role.WITCH)
        target = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, target.player_id)

        self.assertIsNone(get_witch_kill_target(state, witch.player_id))

    def test_empty_wolf_kill_has_no_target_for_witch(self) -> None:
        state = controlled_game(seed=248)
        witch = player_with_role(state, Role.WITCH)
        target = player_with_role(state, Role.VILLAGER)
        advance_to_wolf_kill(state)
        select_wolf_kill(state, state.wolf_captain_id, None)
        seer = player_with_role(state, Role.SEER)
        submit_seer_check(state, seer.player_id, target.player_id)

        self.assertEqual(state.phase, Phase.NIGHT_WITCH_ACTION)
        self.assertIsNone(get_witch_kill_target(state, witch.player_id))

    def test_witch_cannot_act_twice_or_target_dead_player(self) -> None:
        state = controlled_game(seed=245)
        witch = player_with_role(state, Role.WITCH)
        target = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, target.player_id)
        submit_witch_action(state, witch.player_id, "antidote", target.player_id)

        with self.assertRaises(ValueError):
            submit_witch_action(state, witch.player_id, "poison", target.player_id)

        dead_target_state = controlled_game(seed=246)
        witch = player_with_role(dead_target_state, Role.WITCH)
        target = player_with_role(dead_target_state, Role.VILLAGER)
        advance_to_witch(dead_target_state, target.player_id)
        target.is_alive = False
        with self.assertRaises(ValueError):
            submit_witch_action(
                dead_target_state,
                witch.player_id,
                "poison",
                target.player_id,
            )


class NightResolutionTests(TestCase):
    def test_empty_wolf_kill_produces_no_deaths(self) -> None:
        state = controlled_game(seed=250)
        witch = player_with_role(state, Role.WITCH)
        advance_to_wolf_kill(state)
        select_wolf_kill(state, state.wolf_captain_id, None)
        seer = player_with_role(state, Role.SEER)
        target = player_with_role(state, Role.VILLAGER)
        submit_seer_check(state, seer.player_id, target.player_id)
        submit_witch_action(state, witch.player_id, "none")

        resolve_night(state)

        self.assertEqual(state.night_result.death_ids, [])
        self.assertEqual(state.phase, Phase.DAY_ANNOUNCEMENT)

    def test_antidote_prevents_wolf_kill(self) -> None:
        state = controlled_game(seed=251)
        witch = player_with_role(state, Role.WITCH)
        target = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, target.player_id)
        submit_witch_action(state, witch.player_id, "antidote", target.player_id)

        resolve_night(state)

        self.assertEqual(state.phase, Phase.DAY_ANNOUNCEMENT)
        self.assertEqual(state.night_result.death_ids, [])
        self.assertTrue(target.is_alive)

    def test_wolf_captain_can_kill_self(self) -> None:
        state = controlled_game(seed=2511)
        witch = player_with_role(state, Role.WITCH)
        advance_to_wolf_kill(state)
        captain = get_player(state, state.wolf_captain_id)
        select_wolf_kill(state, captain.player_id, captain.player_id)
        seer = player_with_role(state, Role.SEER)
        target = player_with_role(state, Role.VILLAGER)
        submit_seer_check(state, seer.player_id, target.player_id)
        submit_witch_action(state, witch.player_id, "none")

        resolve_night(state)

        self.assertFalse(captain.is_alive)
        self.assertEqual(
            state.night_result.death_causes[captain.player_id],
            ["wolf_kill"],
        )

    def test_wolf_killed_hunter_is_eligible_to_shoot(self) -> None:
        state = controlled_game(seed=252)
        hunter = player_with_role(state, Role.HUNTER)
        witch = player_with_role(state, Role.WITCH)
        advance_to_witch(state, hunter.player_id)
        submit_witch_action(state, witch.player_id, "none")

        resolve_night(state)

        self.assertFalse(hunter.is_alive)
        self.assertTrue(state.night_result.hunter_can_shoot)
        self.assertEqual(state.phase, Phase.NIGHT_HUNTER_SHOT)

    def test_poisoned_hunter_cannot_shoot(self) -> None:
        state = controlled_game(seed=253)
        hunter = player_with_role(state, Role.HUNTER)
        witch = player_with_role(state, Role.WITCH)
        villager = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, villager.player_id)
        submit_witch_action(state, witch.player_id, "poison", hunter.player_id)

        resolve_night(state)

        self.assertFalse(state.night_result.hunter_can_shoot)
        self.assertEqual(state.night_result.death_causes[hunter.player_id], ["poisoned"])
        self.assertEqual(state.phase, Phase.DAY_ANNOUNCEMENT)

    def test_same_target_records_two_causes_once(self) -> None:
        state = controlled_game(seed=254)
        hunter = player_with_role(state, Role.HUNTER)
        witch = player_with_role(state, Role.WITCH)
        advance_to_witch(state, hunter.player_id)
        submit_witch_action(state, witch.player_id, "poison", hunter.player_id)

        resolve_night(state)

        death_events = [
            event
            for event in state.events
            if event.event_type is EventType.PLAYER_DIED
            and event.target_id == hunter.player_id
        ]
        self.assertEqual(len(death_events), 1)
        self.assertEqual(
            state.night_result.death_causes[hunter.player_id],
            ["wolf_kill", "poisoned"],
        )
        self.assertFalse(state.night_result.hunter_can_shoot)

    def test_death_causes_are_hidden_from_players(self) -> None:
        state = controlled_game(seed=255)
        witch = player_with_role(state, Role.WITCH)
        hunter = player_with_role(state, Role.HUNTER)
        viewer = next(
            player
            for player in state.players
            if player.role is Role.VILLAGER
        )
        advance_to_witch(state, hunter.player_id)
        submit_witch_action(state, witch.player_id, "none")

        resolve_night(state)

        player_death_event = next(
            event
            for event in get_visible_events(state, viewer)
            if event.event_type is EventType.PLAYER_DIED
        )
        spectator_death_event = next(
            event
            for event in get_visible_events(state, SPECTATOR_VIEW)
            if event.event_type is EventType.PLAYER_DIED
        )
        self.assertNotIn("causes", player_death_event.data)
        self.assertEqual(spectator_death_event.data["causes"], ["wolf_kill"])

    def test_resolution_rejects_missing_or_repeated_action(self) -> None:
        state = controlled_game(seed=256)
        witch = player_with_role(state, Role.WITCH)
        target = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, target.player_id)

        with self.assertRaises(ValueError):
            resolve_night(state)

        submit_witch_action(state, witch.player_id, "none")
        resolve_night(state)
        with self.assertRaises(ValueError):
            resolve_night(state)

    def test_night_deaths_can_end_game_and_reveal_causes(self) -> None:
        state = controlled_game(seed=257)
        wolves = sorted(
            (
                player
                for player in state.players
                if player.role is Role.WEREWOLF
            ),
            key=lambda player: player.seat,
        )
        wolves[1].is_alive = False
        wolves[2].is_alive = False
        target = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, target.player_id)
        witch = player_with_role(state, Role.WITCH)
        captain = get_player(state, state.wolf_captain_id)
        submit_witch_action(state, witch.player_id, "poison", captain.player_id)

        resolve_night(state)

        self.assertEqual(state.phase, Phase.END)
        self.assertEqual(check_winner(state), Team.GOOD)
        winner_event = next(
            event
            for event in get_visible_events(state, target)
            if event.event_type is EventType.WINNER_DECIDED
        )
        revealed_death = next(
            event
            for event in get_visible_events(state, target)
            if event.event_type is EventType.PLAYER_DIED
            and event.target_id == captain.player_id
        )
        self.assertEqual(winner_event.data["winner"], "good")
        self.assertEqual(revealed_death.data["causes"], ["poisoned"])
