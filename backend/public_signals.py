"""Lightweight extraction of public claims from in-game speech.

The engine already hides private information, but a rule policy that never
reads what other players said cannot respond to it. This module turns the
public speech log into three crude but auditable signals:

* role claims ("我是预言家", "我是女巫", ...)
* accusations ("怀疑 5 号", "票 5 号", "5 号是狼")
* reported seer results ("我验了 5 号是狼", "6 号金水")

Only events already visible to the viewer are read, so a villager can never
learn a wolf's identity through this path.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re

from .game_engine import EventType, GameState, Player, get_visible_events


SPEECH_EVENTS = frozenset(
    {EventType.PUBLIC_SPEECH, EventType.LAST_WORDS, EventType.WOLF_SPEECH}
)
PUBLIC_SPEECH_EVENTS = frozenset(
    {EventType.PUBLIC_SPEECH, EventType.LAST_WORDS}
)

ROLE_KEYWORDS = {
    "预言家": "seer",
    "女巫": "witch",
    "猎人": "hunter",
    "村民": "villager",
    "平民": "villager",
}

_CLAIM = re.compile(r"我(?:是|就是)\s*(预言家|女巫|猎人|村民|平民)")
_NEGATED = re.compile(r"(?:不是|并非|别信|假冒)\s*$")
_ACCUSE_PREFIX = re.compile(
    r"(?:怀疑|票|投|出|归票|抗推)\s*(\d{1,2})\s*号"
)
_ACCUSE_SUFFIX = re.compile(
    r"(\d{1,2})\s*号\s*(?:是狼|是匹狼|有问题|很狼|像狼|划水|是狼人)"
)
_ACCUSE_BARE = re.compile(
    r"(?:票|投|归票)\s*(\d{1,2})(?!\d)(?!\s*号)"
)
_SEER_REPORT = re.compile(
    r"(\d{1,2})\s*号\s*(?:是|为)?\s*(?:狼人|狼|查杀|好人|金水)"
)
_SEER_GIFT = re.compile(r"(?:给|验|发)\s*(\d{1,2})\s*号\s*(金水|查杀)")
_SEER_BARE_GIFT = re.compile(r"(?<!\d)(\d{1,2})\s*(金水|查杀)")


@dataclass(frozen=True, slots=True)
class PublicSignals:
    """Aggregated, viewer-scoped reading of the public speech log."""

    claims: dict[int, frozenset[str]] = field(default_factory=dict)
    accusations: Counter = field(default_factory=Counter)
    seer_reports: dict[int, str] = field(default_factory=dict)
    spoken_seats: frozenset[int] = frozenset()

    def claimed_seats(self, roles: frozenset[str]) -> set[int]:
        return {
            seat
            for seat, claimed in self.claims.items()
            if claimed & roles
        }

    def top_accused(
        self,
        *,
        exclude: int | None = None,
        minimum: int = 1,
    ) -> int | None:
        ranked = [
            (seat, count)
            for seat, count in self.accusations.items()
            if count >= minimum and seat != exclude
        ]
        if not ranked:
            return None
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[0][0]

    def reported_wolves(self) -> list[int]:
        return [
            seat
            for seat, result in self.seer_reports.items()
            if result == "wolf"
        ]


def _seat_of(players: list[Player], player_id: str | None) -> int | None:
    if not player_id:
        return None
    for player in players:
        if player.player_id == player_id:
            return player.seat
    return None


def _claims(text: str) -> set[str]:
    found: set[str] = set()
    for match in _CLAIM.finditer(text):
        prefix = text[max(0, match.start() - 3) : match.start()]
        if _NEGATED.search(prefix):
            continue
        role = ROLE_KEYWORDS.get(match.group(1))
        if role:
            found.add(role)
    return found


def parse_speech(text: str) -> tuple[set[str], Counter, dict[int, str]]:
    """Parse one speech string into (role claims, accusations, reports)."""

    if not isinstance(text, str) or not text:
        return set(), Counter(), {}
    claims = _claims(text)
    accusations: Counter = Counter()
    for pattern in (_ACCUSE_PREFIX, _ACCUSE_SUFFIX, _ACCUSE_BARE):
        for match in pattern.finditer(text):
            seat = int(match.group(1))
            if 1 <= seat <= 12:
                accusations[seat] += 1
    reports: dict[int, str] = {}
    for match in _SEER_REPORT.finditer(text):
        seat = int(match.group(1))
        tail = match.group(0)
        reports[seat] = (
            "good" if ("金水" in tail or "好人" in tail) else "wolf"
        )
    for match in _SEER_GIFT.finditer(text):
        seat = int(match.group(1))
        reports[seat] = "good" if match.group(2) == "金水" else "wolf"
    for match in _SEER_BARE_GIFT.finditer(text):
        seat = int(match.group(1))
        reports[seat] = "good" if match.group(2) == "金水" else "wolf"
    return claims, accusations, reports


def build_signals(state: GameState, viewer: Player) -> PublicSignals:
    """Read only the events this viewer is allowed to see."""

    players = list(state.players)
    claims: dict[int, set[str]] = {}
    accusations: Counter = Counter()
    checks_by_speaker: dict[int, set[int]] = {}
    report_events: list[tuple[int, dict[int, str]]] = []
    spoken: set[int] = set()
    for event in get_visible_events(state, viewer):
        if event.event_type not in SPEECH_EVENTS:
            continue
        content = event.data.get("content")
        if not isinstance(content, str):
            continue
        speaker_seat = _seat_of(players, event.actor_id)
        found_claims, found_accusations, found_reports = parse_speech(content)
        if event.event_type not in PUBLIC_SPEECH_EVENTS:
            continue
        if speaker_seat is not None:
            spoken.add(speaker_seat)
            claims.setdefault(speaker_seat, set()).update(found_claims)
        for seat, count in found_accusations.items():
            # A speaker naming their own seat is self-identification.
            if seat == speaker_seat:
                continue
            accusations[seat] += count
        # A bare "5号是狼" is an accusation, not a seer report. Only a
        # speaker who has claimed seer (in this speech or earlier) can turn
        # it into a check result; otherwise a wolf could hijack the channel
        # by naming a target first.
        if speaker_seat is not None and "seer" in claims.get(
            speaker_seat, set()
        ):
            checks_by_speaker.setdefault(speaker_seat, set()).update(
                found_reports
            )
            if found_reports:
                report_events.append((speaker_seat, found_reports))
    # A seer checks exactly one player per night. On day N only N nights
    # have passed, so anyone reporting more distinct checks than that is
    # contradicting a hard rule; their reports must not become "evidence".
    max_checks = max(1, state.day)
    valid_speakers = {
        seat
        for seat, targets in checks_by_speaker.items()
        if len(targets) <= max_checks
    }
    reports: dict[int, str] = {}
    for speaker, found in report_events:
        if speaker in valid_speakers:
            reports.update(found)
    return PublicSignals(
        claims={
            seat: frozenset(values)
            for seat, values in claims.items()
            if seat and values
        },
        accusations=accusations,
        seer_reports=reports,
        spoken_seats=frozenset(spoken),
    )
