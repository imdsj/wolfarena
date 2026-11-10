"""Cheap repetition checks for generated in-game speech."""

from __future__ import annotations


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
