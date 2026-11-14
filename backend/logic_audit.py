"""Deterministic contradiction checks over the public speech log.

The engine guarantees that a player cannot *read* another player's hidden
role, but a language model can still *say* something that only a wolf could
know. This module turns those slips into auditable findings so the rule
policy and the next prompt can react without trusting the model to police
itself.

Only events visible to the viewer are read.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re

from .game_engine import EventType, GameState, Player, get_visible_events
from .public_signals import parse_speech


PUBLIC_EVENTS = frozenset(
    {EventType.PUBLIC_SPEECH, EventType.LAST_WORDS}
)

IDENTITY_ROLES = {
    "预言家": "seer",
    "女巫": "witch",
    "猎人": "hunter",
}
ROLE_LABELS = {
    "seer": "预言家",
    "witch": "女巫",
    "hunter": "猎人",
}

# "3号才是真预言家" / "3号是预言家" / "3号就是女巫".
_IDENTITY_ASSERTION = re.compile(
    r"(?<!\d)(\d{1,2})\s*号\s*"
    r"(?:才|就|肯定|一定|确实|真的|应该)?\s*"
    r"(?:是|就是)\s*(?:真正的|真)?\s*(预言家|女巫|猎人)"
)
_SELF_CLAIM = re.compile(r"我(?:是|就是)\s*(预言家|女巫|猎人)")
_DEAD_CLAIM = re.compile(
    r"(?<!\d)(\d{1,2})\s*号\s*(?:已经|已|早就)?\s*(?:是)?\s*"
    r"(?:死了|出局了|出局|被淘汰|没了|凉了|死人)"
)
_KILL_TARGET = re.compile(
    r"(?:刀|杀|带走|做掉|处理|集火)\s*(\d{1,2})\s*号?"
    r"|刀口\s*(?:定|在|是|为|选)?\s*(\d{1,2})\s*号?"
)
_VOTE_TARGET = re.compile(
    r"(?:票|投|归票|抗推|放逐|出)\s*(\d{1,2})\s*号?"
)
_KILL_KNOWLEDGE = re.compile(
    r"被刀的人(?:自己)?(?:心里)?有数"
    r"|知道(?:谁)?被刀"
    r"|知道刀口"
    r"|刀口是"
    r"|我清楚刀口"
    r"|被刀的是"
)
_CALL_TO_VOTE = re.compile(
    r"(?:归票|票|投|抗推|放逐)\s*(\d{1,2})\s*号?"
)
_SELF_COUNTERCLAIM = re.compile(
    r"(?:我|本人)\s*(?:是|就是|在|来|要|负责|选择|准备)?\s*"
    r"(?:悍跳|焊跳|对跳)(?:预言家)?"
    r"|(?:我|本人)\s*(?:是|就是)\s*(?:狼人|狼|假预言家|假的预言家)"
)
_SPOKEN_DENIAL = re.compile(
    r"(?<!\d)(\d{1,2})\s*号\s*"
    r"(?:还|也|都)?\s*"
    r"(?:没|没有|尚未|还未|未)\s*"
    r"(?:开口|发言|说话|表态)"
    r"|(?<!\d)(\d{1,2})\s*号\s*(?:的)?\s*发言前"
)
_UNFOUNDED_ACCUSATION = re.compile(
    r"(?<!\d)(\d{1,2})\s*号\s*"
    r"(?:有点问题|有问题|可疑|不对劲|像狼|是狼|要出|要票)"
    r"|(?:怀疑|压|踩|咬|盯)\s*(\d{1,2})\s*号"
    r"|我看\s*(\d{1,2})\s*号\s*"
    r"(?:有点问题|有问题|可疑|不对劲|像狼|是狼)"
)
_UNCLAIMED_CHECK_PROMPT = re.compile(
    r"(?<!\d)(\d{1,2})\s*号\s*(?:你)?\s*(?:就|快|先|来)?\s*"
    r"(?:报|报一下|说说|讲|讲清楚|交出)(?:你的)?(?:查验|验人|查验链)"
    r"|(?:让|请|叫)\s*(\d{1,2})\s*号\s*"
    r"(?:报|报一下|说说|讲)(?:你的)?(?:查验|验人|查验链)"
)

_NEGATED_PREFIX = ("不", "非", "假", "冒", "装", "别")
_HEDGED_PREFIX = ("认", "觉得", "认为", "猜", "可能", "大概", "也许", "如果", "假如", "要是", "若")
_QUESTION_SUFFIX = ("吗", "么", "？", "?", "的话", "还是")


@dataclass(frozen=True, slots=True)
class Finding:
    """One contradiction that a human could have spotted."""

    kind: str
    speaker_seat: int
    subject_seat: int
    detail: str
    weight: int


def _seat_of(players: list[Player], player_id: str | None) -> int | None:
    if not player_id:
        return None
    for player in players:
        if player.player_id == player_id:
            return player.seat
    return None


def _hedged(text: str, start: int, end: int) -> bool:
    prefix = text[max(0, start - 6) : start]
    if any(word in prefix for word in _NEGATED_PREFIX):
        return True
    if any(word in prefix for word in _HEDGED_PREFIX):
        return True
    suffix = text[end : end + 3]
    return any(suffix.startswith(word) for word in _QUESTION_SUFFIX)


def _called_vote_targets(text: str) -> set[int]:
    """Return seats the speech explicitly calls to vote out."""

    if not isinstance(text, str) or not text:
        return set()
    found: set[int] = set()
    for match in _CALL_TO_VOTE.finditer(text):
        prefix = text[max(0, match.start() - 2) : match.start()]
        if "不" in prefix or "别" in prefix:
            continue
        seat = int(match.group(1))
        if 1 <= seat <= 12:
            found.add(seat)
    return found


def audit(state: GameState, viewer: Player) -> tuple[Finding, ...]:
    """Return contradictions visible to ``viewer`` in chronological order."""

    players = list(state.players)
    seat_set = {player.seat for player in players}
    alive_seats = {player.seat for player in players if player.is_alive}
    dead_seats = seat_set - alive_seats
    spoken: set[int] = set()
    spoken_by_day: dict[int, set[int]] = {}
    claims: dict[int, set[str]] = {}
    seer_checks: dict[int, set[int]] = {}
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    # Public vote history lets us catch a speaker who tells the table to
    # vote one way and then casts a different ballot.
    votes_by_day: dict[int, dict[int, int | None]] = {}
    for event in get_visible_events(state, viewer):
        if event.event_type is not EventType.VOTE_RESULT:
            continue
        raw = event.data.get("votes")
        if not isinstance(raw, dict):
            continue
        row: dict[int, int | None] = {}
        for voter_id, target_id in raw.items():
            voter_seat = _seat_of(players, str(voter_id))
            if voter_seat is None:
                continue
            row[voter_seat] = (
                _seat_of(players, str(target_id)) if target_id else None
            )
        votes_by_day[int(event.day)] = row

    for event in get_visible_events(state, viewer):
        if event.event_type not in PUBLIC_EVENTS:
            continue
        speaker = _seat_of(players, event.actor_id)
        if speaker is None:
            continue
        content = event.data.get("content")
        if isinstance(content, str) and content:
            current_day_spoken = spoken_by_day.setdefault(int(event.day), set())
            if admits_deception(content):
                key = ("self_counterclaim", speaker, speaker)
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        Finding(
                            kind="self_counterclaim",
                            speaker_seat=speaker,
                            subject_seat=speaker,
                            detail=(
                                f"{speaker}号公开发言自认悍跳或伪装身份，"
                                "等于主动承认自己不是真预言家"
                            ),
                            weight=5,
                        )
                    )

            denied_seat = spoken_denial(content, current_day_spoken)
            if denied_seat is not None:
                key = ("spoken_denial", speaker, denied_seat)
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        Finding(
                            kind="spoken_denial",
                            speaker_seat=speaker,
                            subject_seat=denied_seat,
                            detail=(
                                f"{speaker}号说{denied_seat}号还没发言，"
                                f"但{denied_seat}号今天已经公开发言，"
                                "与发言记录直接矛盾"
                            ),
                            weight=4,
                        )
                    )

            unspoken_seats = alive_seats - current_day_spoken - {speaker}
            accused_seat = unfounded_unspoken_accusation(
                content,
                unspoken_seats,
            )
            if accused_seat is not None:
                key = ("unfounded_unspoken_accusation", speaker, accused_seat)
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        Finding(
                            kind="unfounded_unspoken_accusation",
                            speaker_seat=speaker,
                            subject_seat=accused_seat,
                            detail=(
                                f"{speaker}号在{accused_seat}号尚未发言、"
                                "也没有公开证据时直接怀疑对方，属于无依据定罪"
                            ),
                            weight=3,
                        )
                    )

            seer_claimants = {
                seat for seat, roles in claims.items() if "seer" in roles
            }
            prompted_seat = prompts_unclaimed_check(
                content,
                seer_claimants,
                speaker,
            )
            if prompted_seat is not None:
                key = ("unclaimed_check_prompt", speaker, prompted_seat)
                if key not in seen:
                    seen.add(key)
                    findings.append(
                        Finding(
                            kind="unclaimed_check_prompt",
                            speaker_seat=speaker,
                            subject_seat=prompted_seat,
                            detail=(
                                f"{speaker}号要求尚未自报预言家的{prompted_seat}号"
                                "报查验，像提前知道对方身份并在公开频道递话"
                            ),
                            weight=4,
                        )
                    )

            # A speaker who claims two different god roles is contradicting
            # themselves, whatever their real role is.
            for match in _SELF_CLAIM.finditer(content):
                role = IDENTITY_ROLES[match.group(1)]
                prefix = content[max(0, match.start() - 3) : match.start()]
                if any(word in prefix for word in _NEGATED_PREFIX):
                    continue
                prior = claims.setdefault(speaker, set())
                if prior and role not in prior:
                    previous = ROLE_LABELS[sorted(prior)[0]]
                    key = ("role_flip", speaker, speaker)
                    if key not in seen:
                        seen.add(key)
                        findings.append(
                            Finding(
                                kind="role_flip",
                                speaker_seat=speaker,
                                subject_seat=speaker,
                                detail=(
                                    f"{speaker}号先自称{previous}，"
                                    f"后又自称{ROLE_LABELS[role]}，"
                                    "身份前后矛盾"
                                ),
                                weight=3,
                            )
                        )
                prior.add(role)

            # Naming an unspoken player's god role is information the speaker
            # cannot have unless they are on that player's team.
            for match in _IDENTITY_ASSERTION.finditer(content):
                subject = int(match.group(1))
                label = match.group(2)
                if subject == speaker or subject not in seat_set:
                    continue
                if subject in spoken:
                    continue
                if _hedged(content, match.start(), match.end()):
                    continue
                key = ("impossible_identity", speaker, subject)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        kind="impossible_identity",
                        speaker_seat=speaker,
                        subject_seat=subject,
                        detail=(
                            f"{speaker}号在{subject}号还没发言时，"
                            f"就断言{subject}号是{label}，"
                            "这是不可能知道的信息"
                        ),
                        weight=4,
                    )
                )

            # Saying a living player is dead is a board-state error. It is
            # weaker than a god-role leak but still worth calling out.
            for match in _DEAD_CLAIM.finditer(content):
                subject = int(match.group(1))
                if subject not in alive_seats:
                    continue
                if "不是" in match.group(0):
                    continue
                if _hedged(content, match.start(), match.end()):
                    continue
                key = ("living_dead_claim", speaker, subject)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        kind="living_dead_claim",
                        speaker_seat=speaker,
                        subject_seat=subject,
                        detail=(
                            f"{speaker}号把还活着的{subject}号"
                            "说成已经出局"
                        ),
                        weight=3,
                    )
                )

            # "1号是金水，今天票1号" contradicts the speaker's own report.
            _, accusations, reports = parse_speech(content)
            for subject, result in reports.items():
                if result != "good" or accusations.get(subject, 0) <= 0:
                    continue
                key = ("report_vs_vote", speaker, subject)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        kind="report_vs_vote",
                        speaker_seat=speaker,
                        subject_seat=subject,
                        detail=(
                            f"{speaker}号刚说{subject}号是好人/金水，"
                            f"又要票{subject}号，前后矛盾"
                        ),
                        weight=3,
                    )
                )

            # Calling for a vote on a player who is already out is a hard
            # board-state error, not a debatable read.
            for subject in dead_vote_targets(content, dead_seats):
                key = ("vote_dead_target", speaker, subject)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    Finding(
                        kind="vote_dead_target",
                        speaker_seat=speaker,
                        subject_seat=subject,
                        detail=(
                            f"{speaker}号还在号召票已经出局的{subject}号，"
                            "而死人是不能投票、也不能被票的"
                        ),
                        weight=3,
                    )
                )

            # Telling the table to vote one seat and then voting another is
            # a direct behavioural contradiction.
            day_votes = votes_by_day.get(int(event.day), {})
            actual = day_votes.get(speaker)
            if actual is not None:
                for subject in _called_vote_targets(content):
                    if subject == speaker or subject not in alive_seats:
                        continue
                    if subject == actual:
                        continue
                    key = ("speech_vote_mismatch", speaker, subject)
                    if key in seen:
                        continue
                    seen.add(key)
                    findings.append(
                        Finding(
                            kind="speech_vote_mismatch",
                            speaker_seat=speaker,
                            subject_seat=subject,
                            detail=(
                                f"{speaker}号白天号召票{subject}号，"
                                f"实际却投了{actual}号，言行不一"
                            ),
                            weight=3,
                        )
                    )

            # A seer checks exactly one player per night; on day N at most N
            # checks can exist. Reporting more is a hard rule violation.
            if "seer" in claims.get(speaker, set()) and reports:
                seer_checks.setdefault(speaker, set()).update(reports)
                allowed = max(1, state.day)
                if len(seer_checks[speaker]) > allowed:
                    key = ("impossible_seer_checks", speaker, 0)
                    if key not in seen:
                        seen.add(key)
                        findings.append(
                            Finding(
                                kind="impossible_seer_checks",
                                speaker_seat=speaker,
                                subject_seat=speaker,
                                detail=(
                                    f"{speaker}号自称预言家，却报了"
                                    f"{len(seer_checks[speaker])}个不同查验；"
                                    f"第{state.day}天最多只有{allowed}次查验，"
                                    "这是硬规则矛盾"
                                ),
                                weight=5,
                            )
                        )
                for clause in re.split(r"[，。；;！!？?\n]", content):
                    if "昨晚" not in clause and "昨夜" not in clause:
                        continue
                    _, _, clause_reports = parse_speech(clause)
                    if len(clause_reports) < 2:
                        continue
                    key = ("one_night_two_checks", speaker, 0)
                    if key in seen:
                        break
                    seen.add(key)
                    findings.append(
                        Finding(
                            kind="one_night_two_checks",
                            speaker_seat=speaker,
                            subject_seat=speaker,
                            detail=(
                                f"{speaker}号在同一晚（昨晚）报了两个查验目标，"
                                "而预言家一晚只能验一人"
                            ),
                            weight=5,
                        )
                    )
                    break
        spoken.add(speaker)
        spoken_by_day.setdefault(int(event.day), set()).add(speaker)

    return tuple(findings)


def suspect_scores(findings: tuple[Finding, ...]) -> Counter:
    """Aggregate findings into a seat -> suspicion score counter."""

    scores: Counter = Counter()
    for finding in findings:
        if finding.kind in {
            "impossible_identity",
            "self_counterclaim",
            "spoken_denial",
            "unfounded_unspoken_accusation",
            "unclaimed_check_prompt",
            "role_flip",
            "impossible_seer_checks",
            "one_night_two_checks",
        }:
            scores[finding.speaker_seat] += finding.weight
    return scores


def admits_deception(text: str) -> bool:
    """True when a public speaker openly admits counter-claiming or being a wolf."""

    return isinstance(text, str) and bool(_SELF_COUNTERCLAIM.search(text))


def spoken_denial(text: str, spoken_seats: set[int]) -> int | None:
    """Return the seat falsely described as silent, if one is present."""

    if not isinstance(text, str) or not text:
        return None
    for match in _SPOKEN_DENIAL.finditer(text):
        raw_seat = match.group(1) or match.group(2)
        seat = int(raw_seat)
        if seat in spoken_seats:
            return seat
    return None


def unfounded_unspoken_accusation(
    text: str,
    unspoken_seats: set[int],
) -> int | None:
    """Return an unspoken seat accused without any public evidence."""

    if not isinstance(text, str) or not text:
        return None
    for match in _UNFOUNDED_ACCUSATION.finditer(text):
        prefix = text[max(0, match.start() - 8) : match.start()]
        if "不" in prefix or "别" in prefix:
            continue
        if "验" in prefix or "查杀" in prefix:
            continue
        if text[match.end() : match.end() + 4].startswith("自刀"):
            continue
        raw_seat = match.group(1) or match.group(2) or match.group(3)
        seat = int(raw_seat)
        if seat in unspoken_seats:
            return seat
    return None


def prompts_unclaimed_check(
    text: str,
    seer_claimants: set[int],
    speaker_seat: int,
) -> int | None:
    """Catch public prompting of a check from someone who never claimed seer."""

    if not isinstance(text, str) or not text:
        return None
    for match in _UNCLAIMED_CHECK_PROMPT.finditer(text):
        seat = int(match.group(1) or match.group(2))
        if seat != speaker_seat and seat not in seer_claimants:
            return seat
    return None


def findings_summary(state: GameState, viewer: Player) -> dict[str, int]:
    """Count each contradiction kind visible to ``viewer``."""

    counts: Counter = Counter()
    for finding in audit(state, viewer):
        counts[finding.kind] += 1
    return dict(counts)


def top_suspect(
    state: GameState,
    viewer: Player,
    *,
    exclude: int | None = None,
    minimum: int = 3,
) -> int | None:
    """Return the most suspicious speaker seat, newest first on a tie."""

    findings = audit(state, viewer)
    scores = suspect_scores(findings)
    if not scores:
        return None
    last_seen: dict[int, int] = {}
    for index, finding in enumerate(findings):
        last_seen[finding.speaker_seat] = index
    ranked = [
        (seat, score, last_seen.get(seat, -1))
        for seat, score in scores.items()
        if score >= minimum and seat != exclude
    ]
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[1], -item[2]))
    return ranked[0][0]


def strongest_finding(
    state: GameState,
    viewer: Player,
    *,
    exclude_speaker: int | None = None,
) -> Finding | None:
    """Return the strongest finding that can be used as an attack point."""

    candidates = [
        finding
        for finding in audit(state, viewer)
        if finding.speaker_seat != exclude_speaker
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.weight, reverse=True)
    return candidates[0]


def asserts_unspoken_identity(
    text: str,
    unspoken_seats: set[int],
    speaker_seat: int,
) -> bool:
    """True when a generated speech names an unspoken player's god role."""

    if not isinstance(text, str) or not text:
        return False
    for match in _IDENTITY_ASSERTION.finditer(text):
        subject = int(match.group(1))
        if subject == speaker_seat or subject not in unspoken_seats:
            continue
        if _hedged(text, match.start(), match.end()):
            continue
        return True
    return False


def speech_claims_living_dead(text: str, alive_seats: set[int]) -> bool:
    """True when a generated speech calls a living player dead."""

    if not isinstance(text, str) or not text:
        return False
    for match in _DEAD_CLAIM.finditer(text):
        subject = int(match.group(1))
        if subject not in alive_seats:
            continue
        if "不是" in match.group(0):
            continue
        if _hedged(text, match.start(), match.end()):
            continue
        return True
    return False


def contradicts_own_report(text: str) -> bool:
    """True when a speech calls a seat good and then votes for it."""

    if not isinstance(text, str) or not text:
        return False
    _, accusations, reports = parse_speech(text)
    return any(
        result == "good" and accusations.get(seat, 0) > 0
        for seat, result in reports.items()
    )


def wolf_speech_targets_dead(text: str, dead_seats: set[int]) -> bool:
    """True when a wolf speech proposes killing an already-dead seat."""

    if not isinstance(text, str) or not text:
        return False
    for match in _KILL_TARGET.finditer(text):
        prefix = text[max(0, match.start() - 2) : match.start()]
        if "不" in prefix or "别" in prefix:
            continue
        seat = int(match.group(1) or match.group(2))
        if seat in dead_seats:
            return True
    return False


def dead_vote_targets(text: str, dead_seats: set[int]) -> set[int]:
    """Return dead seats the speech still tells people to vote out."""

    if not isinstance(text, str) or not text:
        return set()
    found: set[int] = set()
    for match in _VOTE_TARGET.finditer(text):
        prefix = text[max(0, match.start() - 2) : match.start()]
        if "不" in prefix or "别" in prefix:
            continue
        seat = int(match.group(1))
        if seat in dead_seats:
            found.add(seat)
    return found


def impossible_seer_claim_in_text(text: str, day: int) -> bool:
    """True when a generated speech reports more checks than the rules allow."""

    if not isinstance(text, str) or not text:
        return False
    _, _, reports = parse_speech(text)
    if day <= 1 and len(reports) >= 2:
        return True
    for clause in re.split(r"[，。；;！!？?\n]", text):
        if "昨晚" not in clause and "昨夜" not in clause:
            continue
        _, _, clause_reports = parse_speech(clause)
        if len(clause_reports) >= 2:
            return True
    return False


def mentions_two_nights_on_day_one(text: str, day: int) -> bool:
    """True when day 1 speech invents a second night of checks."""

    if day > 1 or not isinstance(text, str):
        return False
    return "两晚" in text or "两夜" in text


def claims_kill_target_knowledge(text: str) -> bool:
    """True when a speech claims to know the night kill target.

    Only wolves (who chose the kill) and a witch holding the antidote know
    this. Any other good player claiming it is either role-claiming by
    accident or leaking information they cannot have.
    """

    if not isinstance(text, str) or not text:
        return False
    return bool(_KILL_KNOWLEDGE.search(text))
