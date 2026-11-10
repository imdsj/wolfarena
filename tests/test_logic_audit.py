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
    contradicts_own_report,
    dead_vote_targets,
    impossible_seer_claim_in_text,
    mentions_two_nights_on_day_one,
    strongest_finding,
    speech_claims_living_dead,
    top_suspect,
    wolf_speech_targets_dead,
)
from backend.public_signals import build_signals, parse_speech


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


class BoardStateTests(TestCase):
    def test_living_player_claimed_dead_is_flagged(self) -> None:
        state = create_game(seed=120, human_count=0)
        speaker = state.players[8]
        subject = state.players[0]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": f"{subject.seat}号已经出局了，别再听他。"},
        )
        findings = audit(state, state.players[0])
        self.assertIn(
            ("living_dead_claim", speaker.seat, subject.seat),
            [(f.kind, f.speaker_seat, f.subject_seat) for f in findings],
        )
        self.assertTrue(
            speech_claims_living_dead(
                f"{subject.seat}号已经出局了", {subject.seat}
            )
        )
        self.assertFalse(
            speech_claims_living_dead(
                f"{subject.seat}号没有出局", {subject.seat}
            )
        )

    def test_gold_water_banish_is_flagged(self) -> None:
        state = create_game(seed=121, human_count=0)
        speaker = state.players[1]
        target = state.players[0]
        content = (
            f"6狼、9金水、{target.seat}金水——"
            f"你{target.seat}号是金水，今天票{target.seat}"
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": content},
        )
        findings = audit(state, state.players[2])
        self.assertIn(
            ("report_vs_vote", speaker.seat, target.seat),
            [(f.kind, f.speaker_seat, f.subject_seat) for f in findings],
        )
        self.assertTrue(contradicts_own_report(content))

    def test_bare_seat_gift_is_parsed(self) -> None:
        _, _, reports = parse_speech("6狼、9金水、1金水")
        self.assertEqual(reports[9], "good")
        self.assertEqual(reports[1], "good")

    def test_seer_never_votes_own_gold_water(self) -> None:
        state = create_game(seed=122, human_count=0)
        seer = next(p for p in state.players if p.role is Role.SEER)
        gold = next(p for p in state.players if p.player_id != seer.player_id)
        accuser = next(
            p
            for p in state.players
            if p.player_id not in {seer.player_id, gold.player_id}
        )
        append_event(
            state,
            EventType.SEER_CHECKED,
            actor_id=seer.player_id,
            target_id=gold.player_id,
            visibility=Visibility.PLAYER,
            visible_to=(seer.player_id,),
            data={"result": "good"},
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=accuser.player_id,
            data={"content": f"{gold.seat}号是狼，今天票{gold.seat}。"},
        )
        picked = L1RulePolicy(seed=122).choose_target(
            state, seer, _view(state, "vote"), choice=None
        )
        self.assertNotEqual(picked, gold.player_id)


class WolfDeadTargetTests(TestCase):
    def test_dead_target_guard(self) -> None:
        self.assertTrue(wolf_speech_targets_dead("今晚定刀2号", {2}))
        self.assertTrue(wolf_speech_targets_dead("今晚刀口在2号", {2}))
        self.assertFalse(wolf_speech_targets_dead("今晚刀5号", {2}))
        self.assertFalse(wolf_speech_targets_dead("不刀2号", {2}))
        self.assertFalse(wolf_speech_targets_dead("别刀2号", {2}))


class VoteDeadTargetTests(TestCase):
    def test_vote_for_dead_seat_is_flagged(self) -> None:
        state = create_game(seed=340, human_count=0)
        speaker = state.players[4]  # seat 5
        dead = state.players[6]  # seat 7
        dead.is_alive = False
        content = f"{dead.seat}号是狼，今天票{dead.seat}"
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": content},
        )
        findings = audit(state, state.players[0])
        self.assertIn(
            ("vote_dead_target", speaker.seat, dead.seat),
            [
                (finding.kind, finding.speaker_seat, finding.subject_seat)
                for finding in findings
            ],
        )
        self.assertEqual(dead_vote_targets(content, {dead.seat}), {dead.seat})
        self.assertEqual(dead_vote_targets("别票7号", {7}), set())


class SeerCheckCountTests(TestCase):
    def test_two_checks_on_day_one_is_impossible(self) -> None:
        state = create_game(seed=320, human_count=0)
        state.day = 1
        speaker = state.players[5]  # seat 6
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={
                "content": "我是预言家，昨晚查验4号是金水、2号是查杀。"
            },
        )
        findings = audit(state, state.players[0])
        kinds = {finding.kind for finding in findings}
        self.assertIn("impossible_seer_checks", kinds)
        self.assertIn("one_night_two_checks", kinds)
        self.assertEqual(top_suspect(state, state.players[0]), speaker.seat)

        signals = build_signals(state, state.players[0])
        self.assertEqual(signals.reported_wolves(), [])

    def test_two_checks_on_day_two_are_allowed(self) -> None:
        state = create_game(seed=321, human_count=0)
        state.day = 2
        speaker = state.players[5]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={
                "content": (
                    "我是预言家，第一晚验4号金水，"
                    "第二晚验2号查杀。"
                )
            },
        )
        findings = audit(state, state.players[0])
        self.assertNotIn(
            "impossible_seer_checks",
            {finding.kind for finding in findings},
        )
        signals = build_signals(state, state.players[0])
        self.assertEqual(signals.reported_wolves(), [2])

    def test_one_night_clause_is_flagged_on_day_two(self) -> None:
        state = create_game(seed=322, human_count=0)
        state.day = 2
        speaker = state.players[5]
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            data={"content": "我是预言家，昨晚查验4号金水、2号查杀。"},
        )
        findings = audit(state, state.players[0])
        self.assertIn(
            "one_night_two_checks",
            {finding.kind for finding in findings},
        )

    def test_two_nights_phrase_on_day_one_is_invalid(self) -> None:
        state = create_game(seed=323, human_count=0)
        state.day = 1
        self.assertTrue(
            mentions_two_nights_on_day_one("6号报的是两晚查验", 1)
        )
        self.assertFalse(
            mentions_two_nights_on_day_one("6号报的是两晚查验", 2)
        )
        self.assertTrue(
            impossible_seer_claim_in_text(
                "我是预言家，昨晚验4号金水、2号查杀", 1
            )
        )
        self.assertFalse(
            impossible_seer_claim_in_text(
                "我是预言家，第一晚验4号金水，第二晚验2号查杀", 2
            )
        )


class WitchPoisonPolicyTests(TestCase):
    def _view(self, state):
        return SimpleNamespace(
            action="witch_action",
            choices=["none", "poison"],
            target_ids=[p.player_id for p in state.players if p.is_alive],
            requires_content=False,
        )

    def test_witch_poisons_a_reported_wolf(self) -> None:
        state = create_game(seed=130, human_count=0)
        witch = next(p for p in state.players if p.role is Role.WITCH)
        claimant = next(
            p for p in state.players if p.player_id != witch.player_id
        )
        target = next(
            p
            for p in state.players
            if p.player_id not in {witch.player_id, claimant.player_id}
        )
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=claimant.player_id,
            data={
                "content": f"我是预言家，我验了{target.seat}号是狼。"
            },
        )
        state.antidote_available = False
        view = self._view(state)
        policy = L1RulePolicy(seed=130)
        choice = policy.choose_choice(state, witch, view)
        self.assertEqual(choice, "poison")
        self.assertEqual(
            policy.choose_target(
                state, witch, view, choice=choice
            ),
            target.player_id,
        )

    def test_witch_holds_poison_without_a_report(self) -> None:
        state = create_game(seed=131, human_count=0)
        witch = next(p for p in state.players if p.role is Role.WITCH)
        state.antidote_available = False
        view = self._view(state)
        self.assertEqual(
            L1RulePolicy(seed=131).choose_choice(state, witch, view),
            "none",
        )
