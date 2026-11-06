"""UI-facing regressions: night banner, hidden system actions, dead last words."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from backend.ai_growth import L1RulePolicy
from backend.actions import available_actions_for_state
from backend.game_engine import (
    DayResult,
    EventType,
    NightResult,
    Phase,
    Role,
    _public_speech_order,
    create_game,
)
from backend.rooms import InMemoryRoomRepository, ViewerAccess
from backend.schemas import ActionRequest
from backend.speech_composer import dead_notice


class NightSummaryTests(TestCase):
    def _state(self, phase: Phase):
        state = create_game(seed=3, human_count=0)
        state.day = 2
        state.phase = phase
        return state

    def test_peaceful_night_is_named(self) -> None:
        state = self._state(Phase.DAY_DISCUSSION)
        state.day_result = DayResult(announced_death_ids=[])
        summary = InMemoryRoomRepository._last_night_summary(state)
        self.assertIsNotNone(summary)
        self.assertIn("平安夜", summary)

    def test_dead_seats_are_listed(self) -> None:
        state = self._state(Phase.DAY_ANNOUNCEMENT)
        victim = state.players[2]
        state.day_result = DayResult(announced_death_ids=[victim.player_id])
        summary = InMemoryRoomRepository._last_night_summary(state)
        self.assertIsNotNone(summary)
        self.assertIn(f"{victim.seat} 号", summary)

    def test_night_phases_hide_the_banner(self) -> None:
        state = self._state(Phase.NIGHT_WOLF_KILL)
        state.day_result = DayResult(announced_death_ids=[])
        self.assertIsNone(
            InMemoryRoomRepository._last_night_summary(state)
        )


class SystemActionVisibilityTests(TestCase):
    def test_host_is_not_offered_manual_phase_buttons(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=1,
            human_count=1,
            max_humans=3,
            nickname="订书机",
        )
        access = ViewerAccess(
            room_id=created.room_id,
            kind="player",
            player_id="p1",
        )
        room = repository._rooms[created.room_id]
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.DAY_ANNOUNCEMENT
            room.state.day_result = DayResult(announced_death_ids=[])
        snapshot = repository.snapshot_for_access(room, access)
        offered = {action.action for action in snapshot.available_actions}
        self.assertNotIn("begin_day", offered)
        self.assertNotIn("resolve_night", offered)
        self.assertNotIn("resolve_vote", offered)
        self.assertIsNotNone(snapshot.last_night_summary)


class DeadLastWordsTests(TestCase):
    def test_last_words_say_the_speaker_is_out(self) -> None:
        state = create_game(seed=5, human_count=0)
        actor = state.players[0]
        state.day_result = DayResult(
            death_causes={actor.player_id: ["hunter_shot"]}
        )
        text = dead_notice(state, actor)
        self.assertIn("已经出局", text)
        self.assertIn("猎人", text)
        self.assertIn("遗言", text)

    def test_wolf_last_words_must_not_concede(self) -> None:
        state = create_game(seed=5, human_count=0)
        wolf = next(p for p in state.players if p.role is Role.WEREWOLF)
        state.day_result = DayResult(
            death_causes={wolf.player_id: ["banished"]}
        )
        text = dead_notice(state, wolf)
        self.assertIn("绝对不能承认自己是狼", text)
        self.assertIn("反咬", text)


class SpeechOrderTests(TestCase):
    """平安夜从 1 号开始；有人死亡从最大死者座位的下一位开始。"""

    def test_peaceful_night_starts_at_seat_one(self) -> None:
        state = create_game(seed=9, human_count=1)
        state.day = 1
        order = _public_speech_order(state, [])
        self.assertEqual(order[0], "p1")
        self.assertEqual(order, [f"p{seat}" for seat in range(1, 10)])

    def test_death_at_seat_three_starts_at_seat_four(self) -> None:
        state = create_game(seed=9, human_count=1)
        state.day = 1
        state.players[2].is_alive = False
        order = _public_speech_order(state, [state.players[2].player_id])
        self.assertEqual(order[0], "p4")
        self.assertEqual(order[-1], "p2")

    def test_death_at_seat_nine_wraps_to_seat_one(self) -> None:
        state = create_game(seed=9, human_count=1)
        state.day = 1
        state.players[8].is_alive = False
        order = _public_speech_order(state, [state.players[8].player_id])
        self.assertEqual(order[0], "p1")


class L1VoteTargetTests(TestCase):
    def test_votes_are_spread_and_never_self(self) -> None:
        state = create_game(seed=42, human_count=0)
        state.day = 2
        ids = [p.player_id for p in state.players if p.is_alive]
        view = SimpleNamespace(
            action="vote",
            target_ids=ids,
            choices=[],
            requires_target=False,
            allow_no_target=True,
            requires_content=False,
        )
        picks = {
            player.player_id: L1RulePolicy(seed=42).choose_target(
                state, player, view, choice=None
            )
            for player in state.players
        }
        self.assertGreater(len(set(picks.values())), 1)
        for actor_id, target in picks.items():
            self.assertNotEqual(actor_id, target)


class WolfKillTargetTests(TestCase):
    def test_wolves_never_kill_teammates_or_always_seat_one(self) -> None:
        state = create_game(seed=13, human_count=0)
        state.day = 1
        ids = [p.player_id for p in state.players if p.is_alive]
        view = SimpleNamespace(
            action="wolf_kill",
            target_ids=ids,
            choices=[],
            requires_target=True,
            allow_no_target=True,
            requires_content=False,
        )
        picks = {
            wolf.player_id: L1RulePolicy(seed=13).choose_target(
                state, wolf, view, choice=None
            )
            for wolf in state.players
            if wolf.role is Role.WEREWOLF
        }
        self.assertGreater(len(set(picks.values())), 1)
        for actor_id, target in picks.items():
            self.assertNotEqual(actor_id, target)
            target_role = next(
                p.role for p in state.players if p.player_id == target
            )
            self.assertIsNot(target_role, Role.WEREWOLF)


class TieVoteGateTests(TestCase):
    def test_tie_vote_freezes_room_even_after_night_advances(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=1, human_count=1, max_humans=3, nickname="x"
        )
        room = repository._rooms[created.room_id]
        access = ViewerAccess(
            room_id=created.room_id, kind="player", player_id="p1"
        )
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.VOTE
            living = [p for p in room.state.players if p.is_alive]
            day_result = DayResult()
            for index, player in enumerate(living):
                day_result.votes[player.player_id] = living[
                    (index + 1) % len(living)
                ].player_id
            day_result.votes_closed = True
            room.state.day_result = day_result
        repository.execute_action(access, ActionRequest(action="resolve_vote"))
        self.assertTrue(room.continue_gate)

    def test_banished_human_gets_last_words_after_continue(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=5, human_count=1, max_humans=3, nickname="t"
        )
        room = repository._rooms[created.room_id]
        access = ViewerAccess(
            room_id=created.room_id, kind="player", player_id="p1"
        )
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.VOTE
            living = [p for p in room.state.players if p.is_alive]
            day_result = DayResult()
            for player in living:
                day_result.votes[player.player_id] = (
                    "p1" if player.player_id != "p1" else "p2"
                )
            day_result.votes_closed = True
            room.state.day_result = day_result
        repository.execute_action(access, ActionRequest(action="resolve_vote"))
        self.assertTrue(room.continue_gate)
        repository.request_continue(created.room_id, access)
        self.assertIs(room.state.phase, Phase.DAY_LAST_WORDS)
        views = available_actions_for_state(
            room.state,
            room.state.players[0],
            host_player_id="p1",
            now=1.0,
        )
        self.assertIn("last_words", [view.action for view in views])

    def test_last_words_pause_before_night(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=7, human_count=1, max_humans=3, nickname="t"
        )
        room = repository._rooms[created.room_id]
        access = ViewerAccess(
            room_id=created.room_id, kind="player", player_id="p1"
        )
        with room.lock:
            room.state.day = 1
            room.state.phase = Phase.VOTE
            living = [p for p in room.state.players if p.is_alive]
            day_result = DayResult()
            for player in living:
                day_result.votes[player.player_id] = (
                    "p8" if player.player_id != "p8" else "p2"
                )
            day_result.votes_closed = True
            room.state.day_result = day_result
        repository.execute_action(access, ActionRequest(action="resolve_vote"))
        self.assertTrue(room.continue_gate)
        repository.request_continue(created.room_id, access)
        self.assertTrue(room.continue_gate)
        self.assertTrue(
            any(
                event.event_type is EventType.LAST_WORDS
                for event in room.state.events
            )
        )


class SeerCheckTargetTests(TestCase):
    def test_seer_checks_vary_and_never_self(self) -> None:
        state = create_game(seed=21, human_count=0)
        state.day = 1
        seer = next(p for p in state.players if p.role is Role.SEER)
        ids = [
            p.player_id
            for p in state.players
            if p.is_alive and p.player_id != seer.player_id
        ]
        view = SimpleNamespace(
            action="seer_check",
            target_ids=ids,
            choices=[],
            requires_target=True,
            allow_no_target=False,
            requires_content=False,
        )
        picks = {
            L1RulePolicy(seed=seed).choose_target(
                state, seer, view, choice=None
            )
            for seed in range(10)
        }
        self.assertGreater(len(picks), 1)
        self.assertNotIn(seer.player_id, picks)


class DayStartAIStallTests(TestCase):
    def test_first_ai_speaker_gets_scheduled_after_begin_day(self) -> None:
        repository = InMemoryRoomRepository()
        created = repository.create_room(
            seed=3, human_count=1, max_humans=3, nickname="h"
        )
        room = repository._rooms[created.room_id]
        with room.lock:
            room.state.day = 2
            room.state.phase = Phase.DAY_ANNOUNCEMENT
            room.state.night_result = NightResult(death_ids=["p2"])
            room.state.players[1].is_alive = False

        repository.advance_ai(created.room_id, now=100.0)
        self.assertIs(room.state.phase, Phase.DAY_DISCUSSION)
        self.assertIsNotNone(room.state.phase_deadline_at)

        repository.process_expired_deadlines(
            room.state.phase_deadline_at + 0.01
        )
        speeches = [
            event
            for event in room.state.events
            if event.event_type is EventType.PUBLIC_SPEECH
        ]
        self.assertTrue(speeches)
