"""Hurry 白天流程验收补充测试。

只覆盖订书机既有白天测试未涉及的边界，不改动业务规则。
每条用例在 docstring 中标注对应规则编号。

2026-10-24 规则变更后更新：
- 遗言上限 30 → 100 个汉字，标点、数字、表情不计入
- 自爆窗口到达 10 秒边界立即关闭
- 公开发言与遗言各 30 秒超时
"""

from unittest import TestCase

from backend.game_engine import (
    LAST_WORDS_TIMEOUT_SECONDS,
    PUBLIC_SPEECH_TIMEOUT_SECONDS,
    SPECTATOR_VIEW,
    EventType,
    Phase,
    Role,
    Team,
    Visibility,
    check_winner,
    close_self_destruct_window,
    get_visible_events,
    resolve_vote,
    self_destruct,
    submit_day_hunter_shot,
    submit_last_words,
    submit_vote,
    timeout_last_words,
)
from tests.test_day_engine import (
    make_day,
    make_vote_day,
    player_with_role,
)


class LastWordsLengthTests(TestCase):
    """规则表第 7 章：每条遗言最多 100 个汉字，标点、数字、表情不计入。"""

    def test_exactly_hundred_han_characters_is_allowed(self) -> None:
        state = make_day(day=1, death_ids=["p4"])

        submit_last_words(state, "p4", "字" * 100)

        self.assertIn("p4", state.day_result.last_words_done)

    def test_hundred_and_one_han_characters_is_rejected(self) -> None:
        state = make_day(day=1, death_ids=["p4"])

        with self.assertRaises(ValueError):
            submit_last_words(state, "p4", "字" * 101)

        self.assertNotIn("p4", state.day_result.last_words_done)

    def test_punctuation_digits_and_emoji_are_not_counted(self) -> None:
        state = make_day(day=1, death_ids=["p4"])
        content = "字" * 100 + "，。！？" * 20 + "1234567890" + "🙂🙂🙂"

        submit_last_words(state, "p4", content)

        self.assertIn("p4", state.day_result.last_words_done)

    def test_punctuation_only_is_allowed(self) -> None:
        state = make_day(day=1, death_ids=["p4"])

        submit_last_words(state, "p4", "，" * 300)

        self.assertIn("p4", state.day_result.last_words_done)


class LastWordsTimeoutTests(TestCase):
    """补充规则第 5 条：每名玩家遗言固定 30 秒，完成或超时后自动推进。"""

    def test_timeout_constants_are_thirty_seconds(self) -> None:
        self.assertEqual(LAST_WORDS_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(PUBLIC_SPEECH_TIMEOUT_SECONDS, 30.0)

    def test_speech_timer_is_armed_after_last_words_timeout(self) -> None:
        """遗言超时推进到公共发言时，必须同时设定 30 秒发言截止时间。

        订书机既有测试已覆盖遗言队列推进与阶段切换，本条只补「交接计时器」
        这一处：若此处漏设，首个发言者会没有倒计时，出现无限等待。
        """

        state = make_day(day=1, death_ids=["p4"], now=100.0)
        self.assertEqual(state.day_result.last_words_deadline, 130.0)

        timeout_last_words(state, 130.0)

        self.assertEqual(state.phase, Phase.DAY_DISCUSSION)
        self.assertIsNotNone(state.day_result.speech_deadline)
        self.assertEqual(
            state.day_result.speech_deadline,
            130.0 + PUBLIC_SPEECH_TIMEOUT_SECONDS,
        )


class SelfDestructWindowTests(TestCase):
    """DESTRUCT-003：自爆取消投票。DESTRUCT-004：窗口最多 10 秒，边界立即关闭。"""

    def test_vote_is_rejected_while_window_is_open(self) -> None:
        state = make_day(day=1)
        wolf = player_with_role(state, Role.WEREWOLF)
        voter = next(
            player
            for player in state.players
            if player.is_alive and player.role is Role.VILLAGER
        )

        self_destruct(state, wolf.player_id, now=100.0)
        self.assertEqual(state.phase, Phase.SELF_DESTRUCT)

        with self.assertRaises(ValueError):
            submit_vote(state, voter.player_id, None)

    def test_self_destruct_at_exact_deadline_is_rejected(self) -> None:
        state = make_day(day=1)
        wolves = sorted(
            (player for player in state.players if player.role is Role.WEREWOLF),
            key=lambda player: player.seat,
        )

        self_destruct(state, wolves[0].player_id, now=100.0)
        self.assertEqual(state.day_result.self_destruct_deadline, 110.0)

        # 边界立即关闭：110.0 不能再自爆
        with self.assertRaises(ValueError):
            self_destruct(state, wolves[1].player_id, now=110.0)

    def test_window_closes_at_deadline(self) -> None:
        state = make_day(day=1)
        wolf = player_with_role(state, Role.WEREWOLF)

        self_destruct(state, wolf.player_id, now=100.0)

        with self.assertRaises(ValueError):
            close_self_destruct_window(state, now=109.9)

        close_self_destruct_window(state, now=110.0)
        self.assertEqual(state.day, 2)


class VoteVisibilityTests(TestCase):
    """变更 3：投票期间不公开票型，结束后 VOTE_RESULT 一次性公开；未投票视为弃权。"""

    def test_vote_cast_is_hidden_from_players_until_vote_ends(self) -> None:
        state = make_vote_day()
        voters = [p for p in state.players if p.is_alive]
        submit_vote(state, voters[0].player_id, voters[1].player_id)

        player_view = get_visible_events(state, voters[2].player_id)
        self.assertEqual(
            sum(1 for e in player_view if e.event_type is EventType.VOTE_CAST),
            0,
        )

        spectator_view = get_visible_events(state, SPECTATOR_VIEW)
        self.assertEqual(
            sum(1 for e in spectator_view if e.event_type is EventType.VOTE_CAST),
            1,
        )

    def test_vote_result_is_public_and_lists_every_living_player(self) -> None:
        state = make_vote_day()
        living = sorted(
            (p for p in state.players if p.is_alive), key=lambda p: p.seat
        )
        target = living[-1]
        for voter in living[:3]:
            submit_vote(state, voter.player_id, target.player_id)
        resolve_vote(state)

        result = next(
            e for e in state.events if e.event_type is EventType.VOTE_RESULT
        )
        self.assertIs(result.visibility, Visibility.PUBLIC)
        self.assertEqual(set(result.data["votes"]), {p.player_id for p in living})
        self.assertEqual(result.data["tally"], {target.player_id: 3})
        self.assertEqual(result.data["banished_id"], target.player_id)
        # 未投票者在结果里记为弃权
        for voter in living[3:]:
            self.assertIsNone(result.data["votes"][voter.player_id])

    def test_uncast_votes_do_not_count_toward_tally(self) -> None:
        state = make_vote_day()
        living = sorted(
            (p for p in state.players if p.is_alive), key=lambda p: p.seat
        )
        submit_vote(state, living[0].player_id, living[1].player_id)
        resolve_vote(state)

        result = next(
            e for e in state.events if e.event_type is EventType.VOTE_RESULT
        )
        self.assertEqual(result.data["tally"], {living[1].player_id: 1})
        self.assertEqual(result.data["banished_id"], living[1].player_id)
        self.assertEqual(
            sum(1 for v in result.data["votes"].values() if v is None),
            len(living) - 1,
        )


class HunterShotWinnerCheckTests(TestCase):
    """VOTE-008 与 WIN-001 的顺序：被带走者先留遗言，再执行胜负检查。"""

    def test_hunter_shot_killing_last_wolf_gives_target_last_words_then_ends(self) -> None:
        state = make_vote_day()
        wolves = sorted(
            (player for player in state.players if player.role is Role.WEREWOLF),
            key=lambda player: player.seat,
        )
        for wolf in wolves[:2]:
            wolf.is_alive = False
        last_wolf = wolves[2]
        self.assertIsNone(check_winner(state))

        hunter = player_with_role(state, Role.HUNTER)
        living = [player for player in state.players if player.is_alive]
        for player in living[:5]:
            submit_vote(state, player.player_id, hunter.player_id)
        for player in living[5:]:
            submit_vote(state, player.player_id, None)
        resolve_vote(state)

        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        submit_last_words(state, hunter.player_id, "带走最后一只狼")
        self.assertEqual(state.phase, Phase.DAY_HUNTER_SHOT)

        submit_day_hunter_shot(state, hunter.player_id, last_wolf.player_id)

        self.assertFalse(last_wolf.is_alive)
        self.assertEqual(check_winner(state), Team.GOOD)
        # VOTE-008：被带走者先获得遗言，此时尚不进入 END
        self.assertEqual(state.phase, Phase.DAY_LAST_WORDS)
        self.assertEqual(state.day_result.last_words_queue, [last_wolf.player_id])

        submit_last_words(state, last_wolf.player_id, "被带走的遗言")

        self.assertEqual(state.phase, Phase.END)
        winner_event = next(
            event
            for event in state.events
            if event.event_type is EventType.WINNER_DECIDED
        )
        self.assertEqual(winner_event.data["winner"], "good")
        self.assertIs(winner_event.visibility, Visibility.PUBLIC)
