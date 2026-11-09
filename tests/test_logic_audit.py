"""Tests for deterministic contradiction detection and its policy use."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from backend.ai_controller import AIController
from backend.ai_growth import L1RulePolicy
from backend.game_engine import (
    EventType,
    Role,
    Visibility,
    append_event,
    create_game,
)
from backend.logic_audit import (
    asserts_unspoken_identity,
    audit,
    strongest_finding,
    top_suspect,
)
from backend.public_signals import build_signals


def _view(state, action: str):
    return SimpleNamespace(
        action=action,
        target_ids=[p.player_id for p in state.players if p.is_alive],
        choices=[],
        requires_content=action in {"speech", "last_words", "wolf_speech"},
    )


class ImpossibleIdentityTests(TestCase):
    def test_flags_claim_before_subject_speaks(self) -> None:
        state = create_game(seed=101, human_count=0)
        speaker = state.players[8]  # seat 9
        subject = state.players[2]  # seat 3
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={
                "content": "5号是狼自刀骗身份，3号才是真预言家。"
            },
        )
        findings = audit(state, state.players[0])
        self.assertEqual(
            [(f.kind, f.speaker_seat, f.subject_seat) for f in findings],
            [("impossible_identity", speaker.seat, subject.seat)],
        )
        self.assertEqual(top_suspect(state, state.players[0]), speaker.seat)

    def test_does_not_flag_after_subject_spoke(self) -> None:
        state = create_game(seed=102, human_count=0)
        speaker = state.players[8]
        subject = state.players[2]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=subject.player_id,
            data={"content": "我先听一轮，过。"},
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "我认3号是预言家，先听他报查验。"},
        )
        self.assertEqual(audit(state, state.players[0]), ())

    def test_question_and_hedge_are_not_findings(self) -> None:
        state = create_game(seed=103, human_count=0)
        speaker = state.players[8]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "3号是预言家吗？还是要再听一轮。"},
        )
        self.assertEqual(audit(state, state.players[0]), ())


class RoleFlipTests(TestCase):
    def test_two_god_claims_are_flagged(self) -> None:
        state = create_game(seed=104, human_count=0)
        speaker = state.players[3]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "我是女巫，昨晚救了一个人。"},
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "其实我是猎人，谁票我我带走谁。"},
        )
        findings = audit(state, state.players[0])
        self.assertEqual(
            [(f.kind, f.speaker_seat) for f in findings],
            [("role_flip", speaker.seat)],
        )


class SpeechGuardTests(TestCase):
    def test_guard_blocks_unspoken_identity_claim(self) -> None:
        self.assertTrue(
            asserts_unspoken_identity("3号才是真预言家", {3}, 9)
        )
        self.assertFalse(
            asserts_unspoken_identity("我是预言家，3号是狼", {3}, 9)
        )
        self.assertFalse(
            asserts_unspoken_identity("3号是预言家吗", {3}, 9)
        )
        self.assertFalse(
            asserts_unspoken_identity("3号刚才说他是预言家", {3}, 9)
        )


class PolicyUseTests(TestCase):
    def test_vote_targets_the_impossible_claim(self) -> None:
        state = create_game(seed=105, human_count=0)
        speaker = state.players[8]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "3号才是真预言家，今天先听他的。"},
        )
        actor = state.players[0]
        policy = L1RulePolicy(seed=105)
        picked = policy.choose_target(
            state, actor, _view(state, "vote"), choice=None
        )
        self.assertEqual(picked, speaker.player_id)

    def test_template_calls_out_the_hole(self) -> None:
        state = create_game(seed=106, human_count=0)
        speaker = state.players[8]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "3号才是真预言家。"},
        )
        actor = next(
            p for p in state.players if p.role is Role.VILLAGER
        )
        text = L1RulePolicy.choose_content(
            state, actor, _view(state, "speech")
        )
        self.assertIn(f"{speaker.seat}号", text)
        self.assertIn("逻辑漏洞", text)

    def test_wolf_follows_the_agreed_kill(self) -> None:
        state = create_game(seed=107, human_count=0)
        wolf = next(p for p in state.players if p.role is Role.WEREWOLF)
        target = next(p for p in state.players if p.role is not Role.WEREWOLF)
        append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={
                "content": (
                    f"收到，刀{target.seat}号不改；白天有人悍跳，"
                    "我咬死他发言虚带节奏，另一个补刀跟票。"
                )
            },
        )
        policy = L1RulePolicy(seed=107)
        picked = policy.choose_target(
            state, wolf, _view(state, "wolf_kill"), choice=None
        )
        self.assertEqual(picked, target.player_id)

    def test_wolf_kill_parser_accepts_kou_phrasing(self) -> None:
        state = create_game(seed=111, human_count=0)
        wolf = next(p for p in state.players if p.role is Role.WEREWOLF)
        target = next(p for p in state.players if p.role is not Role.WEREWOLF)
        append_event(
            state,
            EventType.WOLF_SPEECH,
            actor_id=wolf.player_id,
            visibility=Visibility.WOLVES,
            data={"content": f"今晚刀口在{target.seat}号，不改。"},
        )
        picked = L1RulePolicy(seed=111).choose_target(
            state, wolf, _view(state, "wolf_kill"), choice=None
        )
        self.assertEqual(picked, target.player_id)


class SignalAttributionTests(TestCase):
    def test_plain_accusation_is_not_a_seer_report(self) -> None:
        state = create_game(seed=108, human_count=0)
        speaker = state.players[0]
        target = state.players[4]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": f"{target.seat}号是狼，我先票他。"},
        )
        signals = build_signals(state, speaker)
        self.assertEqual(signals.reported_wolves(), [])
        self.assertGreaterEqual(signals.accusations[target.seat], 1)

    def test_seer_claim_converts_to_a_report(self) -> None:
        state = create_game(seed=109, human_count=0)
        speaker = state.players[0]
        target = state.players[4]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={
                "content": f"我是预言家，我验了{target.seat}号是狼。"
            },
        )
        signals = build_signals(state, speaker)
        self.assertEqual(signals.reported_wolves(), [target.seat])

    def test_strongest_finding_is_exposed(self) -> None:
        state = create_game(seed=110, human_count=0)
        speaker = state.players[8]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "3号才是真预言家。"},
        )
        finding = strongest_finding(state, state.players[0])
        self.assertIsNotNone(finding)
        self.assertEqual(finding.speaker_seat, speaker.seat)


class LogicCatchInjectionTests(TestCase):
    def test_missing_catch_is_prepended_for_good_players(self) -> None:
        state = create_game(seed=112, human_count=0)
        speaker = state.players[8]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "3号才是真预言家。"},
        )
        actor = next(
            p
            for p in state.players
            if p.role is Role.VILLAGER and p.seat != speaker.seat
        )
        text = "我觉得3号有点急，先听听。"
        out = AIController._ensure_logic_catch(
            state, actor, SimpleNamespace(action="speech"), text
        )
        self.assertTrue(out.startswith(f"先抓{speaker.seat}号一个漏洞"))
        self.assertIn(text, out)

    def test_wolf_does_not_parrot_the_catch(self) -> None:
        state = create_game(seed=113, human_count=0)
        speaker = state.players[8]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "3号才是真预言家。"},
        )
        wolf = next(p for p in state.players if p.role is Role.WEREWOLF)
        text = "我觉得3号有点急。"
        out = AIController._ensure_logic_catch(
            state, wolf, SimpleNamespace(action="speech"), text
        )
        self.assertEqual(out, text)
