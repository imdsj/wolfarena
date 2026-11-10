"""Cheap repetition checks for generated in-game speech."""

from __future__ import annotations

import re

_SEAT_LINE = re.compile(r"^\s*(\d{1,2})\s*号\s*[：:]\s*(.+)$")
_QUOTED = re.compile(r"[「『“\"]([^」』”\"]{2,60})[」』”\"]")
_ATTRIBUTION = re.compile(
    r"(\d{1,2})\s*号\s*(?:刚才|刚刚|前面|之前|上轮|这轮)?\s*"
    r"(?:说|讲|提到|表示|认为|称|承认)"
    r"([^。！？；\n]{2,30})"
)
# 只盯「可被证伪的硬事实」，避免把普通评价误判成编造。
_HARD_FACTS = ("平安夜", "查杀", "金水", "自刀", "预言家")


def seat_utterances(lines: list[str]) -> dict[int, str]:
    """Map seat number to everything that seat said, joined without spaces."""

    spoken: dict[int, str] = {}
    for line in lines or []:
        if not isinstance(line, str):
            continue
        match = _SEAT_LINE.match(line)
        if not match:
            continue
        seat = int(match.group(1))
        said = "".join(match.group(2).split())
        spoken[seat] = spoken.get(seat, "") + said
    return spoken


def fabricates_reference(text: str, lines: list[str]) -> bool:
    """True when a speech puts words or facts in a seat's mouth it never said.

    Two narrow rules, both cheap and hard to false-positive:

    1. Anything inside quotation marks must appear in an earlier speech.
    2. "N 号说……" carrying a hard fact requires that seat to have said it.
    """

    if not isinstance(text, str) or not text:
        return False

    everything = "".join("".join(line.split()) for line in lines or [] if isinstance(line, str))
    for quoted in _QUOTED.findall(text):
        compact = "".join(quoted.split())
        if len(compact) >= 4 and compact not in everything:
            return True

    spoken = seat_utterances(lines)
    for match in _ATTRIBUTION.finditer(text):
        seat = int(match.group(1))
        claim = match.group(2)
        facts = [fact for fact in _HARD_FACTS if fact in claim]
        if not facts:
            continue
        said = spoken.get(seat, "")
        if any(fact not in said for fact in facts):
            return True
    return False



def _bigrams(text: str) -> set[str]:
    compact = "".join(character for character in text if not character.isspace())
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def similarity(left: str, right: str) -> float:
    if not isinstance(left, str) or not isinstance(right, str):
        return 0.0
    a = _bigrams(left)
    b = _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_repetitive(
    text: str,
    prior: list[str],
    *,
    threshold: float = 0.82,
) -> bool:
    """True when a speech is a near-copy of something already said."""

    if not isinstance(text, str) or len(text) < 12:
        return False
    return any(
        bool(other) and similarity(text, other) >= threshold
        for other in prior
    )
