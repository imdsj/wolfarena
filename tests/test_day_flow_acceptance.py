"""Hurry 白天流程验收补充测试（2026-10-24）。

只覆盖订书机既有 18 项白天测试未涉及的边界，不改动业务规则。
每条用例在 docstring 中标注对应规则编号。
"""

from unittest import TestCase

from backend.game_engine import (
    EventType,
    Phase,
    Role,
    Team,
    Visibility,
    check_winner,
    resolve_vote,
    self_destruct,
    submit_day_hunter_shot,
    submit_last_words,
    submit_vote,
)
from tests.test_day_engine import (
    make_day,
    make_vote_day,
    player_with_role,
)


class LastWordsBoundaryTests(TestCase):
    """规则表第 7 章：遗言最多 30 个汉字。"""

    def test_exactly_thirty_characters_is_allowed(self) -> None:
        state = make_day(day=1, death_ids=["p4"])

        submit_last_words(state, "p4", "字" * 30)

        self.assertEqual(state.day_result.last_words_done, ["p4"])

    def test_thirty_one_characters_is_rejected(self) -> None:
        state = make_day(day=1, death_ids=["p4"])

        with self.assertRaises(ValueError):
            submit_last_words(state, "p4", "字" * 31)

        self.assertNotIn("p4", state.day_result.last_words_done)


class SelfDestructVoteLockoutTests(TestCase):
    """DESTRUCT-003：自爆立即取消当天投票。DESTRUCT-004：窗口最多 10 秒。"""

    def test_vote_is_rejected_while_self_destruct_window_is_open(self) -> None:
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

    def test_second_self_destruct_after_deadline_is_rejected(self) -> None:
        state = make_day(day=1)
        wolves = sorted(
            (player for player in state.players if player.role is Role.WEREWOLF),
            key=lambda player: player.seat,
        )

        self_destruct(state, wolves[0].player_id, now=100.0)
        self.assertEqual(state.day_result.self_destruct_deadline, 110.0)

        with self.assertRaises(ValueError):
            self_destruct(state, wolves[1].player_id, now=110.1)


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
