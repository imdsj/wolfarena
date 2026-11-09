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


def audit(state: GameState, viewer: Player) -> tuple[Finding, ...]:
    """Return contradictions visible to ``viewer`` in chronological order."""

    players = list(state.players)
    seat_set = {player.seat for player in players}
    alive_seats = {player.seat for player in players if player.is_alive}
    spoken: set[int] = set()
    claims: dict[int, set[str]] = {}
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    for event in get_visible_events(state, viewer):
        if event.event_type not in PUBLIC_EVENTS:
            continue
        speaker = _seat_of(players, event.actor_id)
        if speaker is None:
            continue
        content = event.data.get("content")
        if isinstance(content, str) and content:
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
        spoken.add(speaker)

    return tuple(findings)


def suspect_scores(findings: tuple[Finding, ...]) -> Counter:
    """Aggregate findings into a seat -> suspicion score counter."""

    scores: Counter = Counter()
    for finding in findings:
        if finding.kind in {"impossible_identity", "role_flip"}:
            scores[finding.speaker_seat] += finding.weight
    return scores


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
