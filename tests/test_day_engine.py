"""Tests for daytime speech, self-destruction, voting, and hunter shots."""

from unittest import TestCase

from backend.game_engine import (
    EventType,
    GameState,
    NightResult,
    Phase,
    Role,
    SPECTATOR_VIEW,
    Team,
    Visibility,
    begin_banishment_last_words,
    begin_day,
    check_winner,
    close_vote,
    close_self_destruct_window,
    create_game,
    get_player,
    get_visible_events,
    record_public_speech,
    record_wolf_speech,
    resolve_night,
    resolve_vote,
    select_wolf_kill,
    self_destruct,
    start_night,
    submit_day_hunter_shot,
    submit_last_words,
    submit_night_hunter_shot,
    submit_seer_check,
    submit_vote,
    submit_witch_action,
    timeout_last_words,
    timeout_public_speech,
)


def controlled_game(seed: int = 301) -> GameState:
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


def advance_to_witch(state: GameState, wolf_target_id: str) -> None:
    start_night(state)
    wolves = sorted(
        (
            player
            for player in state.players
            if player.role is Role.WEREWOLF and player.is_alive
        ),
        key=lambda player: player.seat,
    )
    for player in wolves:
        record_wolf_speech(state, player.player_id, 1, f"R1-{player.seat}")
    for player in wolves:
        record_wolf_speech(state, player.player_id, 2, f"R2-{player.seat}")
    select_wolf_kill(state, state.wolf_captain_id, wolf_target_id)
    seer = player_with_role(state, Role.SEER)
    target = player_with_role(state, Role.VILLAGER)
    if target.player_id == seer.player_id:
        target = player_with_role(state, Role.HUNTER)
    submit_seer_check(state, seer.player_id, target.player_id)


def make_day(
    *,
    day: int = 1,
    death_ids: list[str] | None = None,
    now: float | None = None,
) -> GameState:
    state = controlled_game(seed=320 + day)
    state.day = day
    state.phase = Phase.DAY_ANNOUNCEMENT
    state.night_result = NightResult(death_ids=list(death_ids or []))
    for player_id in death_ids or []:
        get_player(state, player_id).is_alive = False
    begin_day(state, now=now)
    return state


def make_vote_day() -> GameState:
    state = make_day(day=1)
    for player_id in list(state.day_result.speech_order):
        record_public_speech(state, player_id, f"发言-{player_id}")
    assert state.phase is Phase.VOTE
    return state


class NightHunterTests(TestCase):
    def test_night_hunter_shot_is_hidden_and_adds_public_death(self) -> None:
        state = controlled_game(seed=301)
        hunter = player_with_role(state, Role.HUNTER)
        witch = player_with_role(state, Role.WITCH)
        target = player_with_role(state, Role.VILLAGER)
        advance_to_witch(state, hunter.player_id)
        submit_witch_action(state, witch.player_id, "none")
        resolve_night(state)
        self.assertEqual(state.phase, Phase.NIGHT_HUNTER_SHOT)

        submit_night_hunter_shot(state, hunter.player_id, target.player_id)

        self.assertFalse(target.is_alive)
        self.assertEqual(state.phase, Phase.DAY_ANNOUNCEMENT)
        spectator_events = get_visible_events(state, SPECTATOR_VIEW)
        villager = next(
            player
            for player in state.players
            if player.role is Role.VILLAGER and player.is_alive
        )
        villager_events = get_visible_events(state, villager)
        self.assertTrue(
            any(event.event_type is EventType.HUNTER_SHOT for event in spectator_events)
        )
        self.assertFalse(
            any(event.event_type is EventType.HUNTER_SHOT for event in villager_events)
        )
        death_event = next(
            event
            for event in villager_events
            if event.event_type is EventType.PLAYER_DIED
            and event.target_id == target.player_id
        )
        self.assertNotIn("causes", death_event.data)

    def test_night_hunter_may_decline_to_shoot(self) -> None:
        state = controlled_game(seed=302)
        hunter = player_with_role(state, Role.HUNTER)
        witch = player_with_role(state, Role.WITCH)
        advance_to_witch(state, hunter.player_id)
        submit_witch_action(state, witch.player_id, "none")
        resolve_night(state)

        submit_night_hunter_shot(state, hunter.player_id, None)

        self.assertEqual(state.phase, Phase.DAY_ANNOUNCEMENT)
        self.assertFalse(state.night_result.hunter_can_shoot)


class DayAnnouncementAndLastWordsTests(TestCase):
    def test_first_day_night_deaths_enter_last_words_in_order(self) -> None:
        state = make_day(day=1, death_ids=["p4", "p2"])

        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        self.assertEqual(state.day_result.last_words_queue, ["p4", "p2"])
        submit_last_words(state, "p4", "第一条遗言")
        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        submit_last_words(state, "p2", "第二条遗言")
        self.assertEqual(state.phase, Phase.DAY_DISCUSSION)

    def test_second_day_night_deaths_have_no_last_words(self) -> None:
        state = make_day(day=2, death_ids=["p4"])

        self.assertEqual(state.phase, Phase.DAY_DISCUSSION)
        self.assertEqual(state.day_result.last_words_queue, [])

    def test_last_words_reject_wrong_actor_duplicate_and_long_content(self) -> None:
        state = make_day(day=1, death_ids=["p4"])
        alive = next(player for player in state.players if player.is_alive)

        with self.assertRaises(ValueError):
            submit_last_words(state, alive.player_id, "活人遗言")
        with self.assertRaises(ValueError):
            submit_last_words(state, "p4", "字" * 101)

        submit_last_words(state, "p4", "字" * 100)
        with self.assertRaises(ValueError):
            submit_last_words(state, "p4", "重复遗言")

    def test_begin_day_rejects_duplicate_start(self) -> None:
        state = make_day(day=1)

        with self.assertRaises(ValueError):
            begin_day(state)

    def test_last_words_limit_counts_han_characters_only(self) -> None:
        allowed_state = make_day(day=1, death_ids=["p4"])
        submit_last_words(allowed_state, "p4", "字" * 100 + "！" * 20)

        rejected_state = make_day(day=1, death_ids=["p4"])
        with self.assertRaises(ValueError):
            submit_last_words(rejected_state, "p4", "字" * 101)
        self.assertEqual(rejected_state.day_result.last_words_queue, ["p4"])

    def test_last_words_timeout_advances_after_fixed_30_seconds(self) -> None:
        state = make_day(day=1, death_ids=["p4", "p2"], now=100.0)
        self.assertEqual(state.day_result.last_words_deadline, 130.0)

        event_count_before = len(state.events)
        with self.assertRaises(ValueError):
            timeout_last_words(state, 129.9)
        self.assertEqual(state.day_result.last_words_queue, ["p4", "p2"])
        self.assertEqual(len(state.events), event_count_before)

        timeout_last_words(state, 130.0)
        self.assertEqual(state.day_result.last_words_queue, ["p2"])
        self.assertEqual(state.day_result.last_words_deadline, 160.0)
        timeout_last_words(state, 160.0)
        self.assertEqual(state.phase, Phase.DAY_DISCUSSION)
        self.assertEqual(state.day_result.last_words_deadline, None)
        timeout_events = [
            event
            for event in state.events
            if event.event_type is EventType.LAST_WORDS_TIMEOUT
        ]
        self.assertEqual(len(timeout_events), 2)


class PublicSpeechTests(TestCase):
    def test_public_speech_is_seat_ordered_and_reaches_vote(self) -> None:
        state = make_day(day=1)
        order = list(state.day_result.speech_order)
        before_phase = state.phase
        before_index = state.day_result.next_speaker_index
        before_event_count = len(state.events)

        with self.assertRaises(ValueError):
            record_public_speech(state, order[1], "抢麦")

        self.assertIs(state.phase, before_phase)
        self.assertEqual(state.day_result.next_speaker_index, before_index)
        self.assertEqual(len(state.events), before_event_count)

        for player_id in order:
            record_public_speech(state, player_id, f"发言-{player_id}")

        self.assertEqual(state.phase, Phase.VOTE)
        speech_events = [
            event
            for event in state.events
            if event.event_type is EventType.PUBLIC_SPEECH
        ]
        self.assertEqual(
            [event.actor_id for event in speech_events],
            order,
        )

    def test_timeout_advances_each_speaker_and_reaches_vote(self) -> None:
        state = make_day(day=1, now=100.0)
        self.assertEqual(state.day_result.speech_deadline, 130.0)

        phase_before = state.phase
        index_before = state.day_result.next_speaker_index
        event_count_before = len(state.events)
        with self.assertRaises(ValueError):
            timeout_public_speech(state, 129.9)
        self.assertIs(state.phase, phase_before)
        self.assertEqual(state.day_result.next_speaker_index, index_before)
        self.assertEqual(len(state.events), event_count_before)

        while state.phase is Phase.DAY_DISCUSSION:
            deadline = state.day_result.speech_deadline
            self.assertIsNotNone(deadline)
            timeout_public_speech(state, deadline)

        self.assertEqual(state.phase, Phase.VOTE)
        timeout_events = [
            event
            for event in state.events
            if event.event_type is EventType.PUBLIC_SPEECH_TIMEOUT
        ]
        self.assertEqual(len(timeout_events), 9)


class SelfDestructTests(TestCase):
    def test_first_self_destruct_cancels_vote_and_opens_window(self) -> None:
        state = make_day(day=1)
        wolf = player_with_role(state, Role.WEREWOLF)

        self_destruct(state, wolf.player_id, now=100.0)

        self.assertFalse(wolf.is_alive)
        self.assertIs(state.phase, Phase.SELF_DESTRUCT)
        self.assertEqual(state.day_result.self_destruct_deadline, 110.0)
        event = next(
            event
            for event in state.events
            if event.event_type is EventType.SELF_DESTRUCTED
        )
        self.assertIs(event.visibility, Visibility.PUBLIC)
        self.assertEqual(event.data["revealed_role"], "werewolf")
        self.assertFalse(event.data["has_last_words"])
        self.assertEqual(state.day_result.last_words_queue, [])

    def test_other_wolves_can_continue_until_window_closes(self) -> None:
        state = make_day(day=1)
        wolves = sorted(
            (
                player
                for player in state.players
                if player.role is Role.WEREWOLF
            ),
            key=lambda player: player.seat,
        )
        self_destruct(state, wolves[0].player_id, now=100.0)
        self_destruct(state, wolves[1].player_id, now=105.0)

        with self.assertRaises(ValueError):
            close_self_destruct_window(state, now=109.9)

        close_self_destruct_window(state)
        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        self.assertEqual(state.day, 2)

    def test_non_wolf_and_late_self_destruct_are_rejected(self) -> None:
        state = make_day(day=1)
        wolf = player_with_role(state, Role.WEREWOLF)
        villager = player_with_role(state, Role.VILLAGER)
        with self.assertRaises(ValueError):
            self_destruct(state, villager.player_id, now=100.0)

        self_destruct(state, wolf.player_id, now=100.0)
        with self.assertRaises(ValueError):
            self_destruct(state, villager.player_id, now=110.0)

        other_wolf = next(
            player
            for player in state.players
            if player.role is Role.WEREWOLF and player.is_alive
        )
        with self.assertRaises(ValueError):
            self_destruct(state, other_wolf.player_id, now=110.0)

    def test_vote_phase_self_destruct_is_rejected(self) -> None:
        state = make_vote_day()
        wolf = player_with_role(state, Role.WEREWOLF)

        with self.assertRaises(ValueError):
            self_destruct(state, wolf.player_id, now=100.0)
        self.assertTrue(wolf.is_alive)
        self.assertIs(state.phase, Phase.VOTE)

    def test_all_wolves_self_destruct_ends_with_good_win(self) -> None:
        state = make_day(day=1)
        wolves = sorted(
            (
                player
                for player in state.players
                if player.role is Role.WEREWOLF
            ),
            key=lambda player: player.seat,
        )
        self_destruct(state, wolves[0].player_id, now=100.0)
        self_destruct(state, wolves[1].player_id, now=101.0)
        self_destruct(state, wolves[2].player_id, now=102.0)

        self.assertEqual(state.phase, Phase.END)
        self.assertEqual(check_winner(state), Team.GOOD)


class VoteTests(TestCase):
    def test_self_vote_abstain_and_last_vote_is_used(self) -> None:
        state = make_vote_day()
        voter = player_with_role(state, Role.VILLAGER)
        first_target = player_with_role(state, Role.WEREWOLF)
        second_target = player_with_role(state, Role.SEER)

        submit_vote(state, voter.player_id, voter.player_id)
        submit_vote(state, voter.player_id, first_target.player_id)
        submit_vote(state, voter.player_id, second_target.player_id)

        self.assertEqual(
            state.day_result.votes[voter.player_id],
            second_target.player_id,
        )
        self.assertFalse(
            any(
                event.event_type is EventType.VOTE_CAST
                for event in get_visible_events(state, voter)
            )
        )
        vote_events = [
            event
            for event in state.events
            if event.event_type is EventType.VOTE_CAST
        ]
        self.assertEqual(len(vote_events), 3)
        self.assertTrue(
            all(event.visibility is Visibility.GOD for event in vote_events)
        )

        close_vote(state)
        resolve_vote(state)
        vote_result = next(
            event
            for event in get_visible_events(state, voter)
            if event.event_type is EventType.VOTE_RESULT
        )
        self.assertEqual(
            vote_result.data["votes"][voter.player_id],
            second_target.player_id,
        )

    def test_close_vote_locks_ballot_and_emits_public_event(self) -> None:
        state = make_vote_day()
        voter = player_with_role(state, Role.VILLAGER)
        target = player_with_role(state, Role.SEER)
        other_target = player_with_role(state, Role.WEREWOLF)
        submit_vote(state, voter.player_id, target.player_id)

        close_vote(state)

        with self.assertRaises(ValueError):
            close_vote(state)
        with self.assertRaises(ValueError):
            submit_vote(state, voter.player_id, other_target.player_id)
        self.assertEqual(state.day_result.votes[voter.player_id], target.player_id)
        close_event = next(
            event
            for event in get_visible_events(state, voter)
            if event.event_type is EventType.VOTE_CLOSED
        )
        self.assertEqual(close_event.data["submitted_votes"], 1)

    def test_resolve_and_banishment_require_separate_steps(self) -> None:
        state = make_vote_day()
        target = player_with_role(state, Role.SEER)
        living = [player for player in state.players if player.is_alive]
        for player in living[:5]:
            submit_vote(state, player.player_id, target.player_id)

        with self.assertRaises(ValueError):
            resolve_vote(state)
        close_vote(state)
        resolve_vote(state)

        self.assertIs(state.phase, Phase.VOTE)
        self.assertTrue(state.day_result.banishment_pending)
        with self.assertRaises(ValueError):
            resolve_vote(state)
        begin_banishment_last_words(state)
        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        started_event = next(
            event
            for event in state.events
            if event.event_type is EventType.BANISHMENT_LAST_WORDS_STARTED
        )
        self.assertEqual(started_event.actor_id, target.player_id)

    def test_zero_votes_and_ties_eliminate_nobody(self) -> None:
        zero_state = make_vote_day()
        for player in zero_state.players:
            if player.is_alive:
                submit_vote(zero_state, player.player_id, None)
        close_vote(zero_state)
        resolve_vote(zero_state)
        self.assertEqual(zero_state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        self.assertTrue(all(player.is_alive for player in zero_state.players))
        with self.assertRaises(ValueError):
            resolve_vote(zero_state)

        tie_state = make_vote_day()
        living = [player for player in tie_state.players if player.is_alive]
        for index, player in enumerate(living[:-1]):
            submit_vote(
                tie_state,
                player.player_id,
                living[index % 2].player_id,
            )
        submit_vote(tie_state, living[-1].player_id, None)
        close_vote(tie_state)
        resolve_vote(tie_state)
        self.assertEqual(tie_state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        self.assertTrue(all(player.is_alive for player in tie_state.players))
        with self.assertRaises(ValueError):
            resolve_vote(tie_state)

    def test_dead_voter_or_dead_target_is_rejected(self) -> None:
        state = make_vote_day()
        voter = player_with_role(state, Role.VILLAGER)
        target = player_with_role(state, Role.SEER)
        voter.is_alive = False

        with self.assertRaises(ValueError):
            submit_vote(state, voter.player_id, target.player_id)

        other_voter = player_with_role(state, Role.WEREWOLF)
        target.is_alive = False
        with self.assertRaises(ValueError):
            submit_vote(state, other_voter.player_id, target.player_id)

    def test_unique_highest_vote_banishes_and_uses_last_words(self) -> None:
        state = make_vote_day()
        target = player_with_role(state, Role.VILLAGER)
        living = [player for player in state.players if player.is_alive]
        for player in living[:5]:
            submit_vote(state, player.player_id, target.player_id)
        for player in living[5:]:
            submit_vote(state, player.player_id, None)

        close_vote(state)
        resolve_vote(state)

        self.assertFalse(target.is_alive)
        self.assertIs(state.phase, Phase.VOTE)
        self.assertTrue(state.day_result.banishment_pending)
        begin_banishment_last_words(state)
        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        self.assertEqual(state.day_result.last_words_queue, [target.player_id])
        submit_last_words(state, target.player_id, "被放逐遗言")
        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        self.assertEqual(state.day, 2)


class DayHunterTests(TestCase):
    def setup_hunter_vote(self) -> tuple[GameState, object]:
        state = make_vote_day()
        hunter = player_with_role(state, Role.HUNTER)
        living = [player for player in state.players if player.is_alive]
        for player in living[:5]:
            submit_vote(state, player.player_id, hunter.player_id)
        for player in living[5:]:
            submit_vote(state, player.player_id, None)
        close_vote(state)
        resolve_vote(state)
        begin_banishment_last_words(state)
        return state, hunter

    def test_banished_hunter_speaks_then_shoots_and_target_speaks(self) -> None:
        state, hunter = self.setup_hunter_vote()
        target = player_with_role(state, Role.VILLAGER)

        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        submit_last_words(state, hunter.player_id, "猎人遗言")
        self.assertEqual(state.phase, Phase.DAY_HUNTER_SHOT)
        submit_day_hunter_shot(state, hunter.player_id, target.player_id)
        self.assertFalse(target.is_alive)
        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        self.assertEqual(state.day_result.last_words_queue, [target.player_id])
        living_viewer = next(
            player
            for player in state.players
            if player.is_alive and player.role is Role.WEREWOLF
        )
        target_death = next(
            event
            for event in get_visible_events(state, living_viewer)
            if event.event_type is EventType.PLAYER_DIED
            and event.target_id == target.player_id
        )
        self.assertNotIn("causes", target_death.data)

        submit_last_words(state, target.player_id, "被带走遗言")
        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)

    def test_banished_hunter_may_not_shoot(self) -> None:
        state, hunter = self.setup_hunter_vote()
        submit_last_words(state, hunter.player_id, "不开枪")
        submit_day_hunter_shot(state, hunter.player_id, None)

        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        no_shot_event = next(
            event
            for event in state.events
            if event.event_type is EventType.HUNTER_SHOT
        )
        self.assertIsNone(no_shot_event.target_id)
        self.assertIs(no_shot_event.visibility, Visibility.GOD)
        living_villager = next(
            player
            for player in state.players
            if player.is_alive and player.role is Role.VILLAGER
        )
        self.assertFalse(
            any(
                event.event_type is EventType.HUNTER_SHOT
                for event in get_visible_events(state, living_villager)
            )
        )


class NextNightCaptainTests(TestCase):
    def test_dead_captain_is_replaced_before_next_night(self) -> None:
        state = controlled_game(seed=350)
        start_night(state)
        old_captain = get_player(state, state.wolf_captain_id)
        wolves = sorted(
            (
                player
                for player in state.players
                if player.role is Role.WEREWOLF
            ),
            key=lambda player: player.seat,
        )
        for player in wolves:
            record_wolf_speech(state, player.player_id, 1, "R1")
        for player in wolves:
            record_wolf_speech(state, player.player_id, 2, "R2")
        select_wolf_kill(state, old_captain.player_id, old_captain.player_id)
        seer = player_with_role(state, Role.SEER)
        target = player_with_role(state, Role.VILLAGER)
        submit_seer_check(state, seer.player_id, target.player_id)
        witch = player_with_role(state, Role.WITCH)
        submit_witch_action(state, witch.player_id, "none")
        resolve_night(state)

        begin_day(state)
        submit_last_words(state, old_captain.player_id, "队长遗言")
        living_wolf = next(
            player
            for player in wolves
            if player.is_alive and player is not old_captain
        )
        self_destruct(state, living_wolf.player_id, now=100.0)
        close_self_destruct_window(state, now=110.0)

        self.assertEqual(state.phase, Phase.NIGHT_WOLF_DISCUSSION_R1)
        self.assertNotEqual(state.wolf_captain_id, old_captain.player_id)
        self.assertTrue(get_player(state, state.wolf_captain_id).is_alive)
