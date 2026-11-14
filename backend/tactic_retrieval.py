"""Dependency-free, structure-aware retrieval over the local tactics library.

No external embedding service is required: the retriever mixes role/phase
filters with explicit board signals (hard contradictions, vote blocs,
counter-claims, potion/gun state) and lexical overlap. It is deterministic and
fully offline, so the same game state always retrieves the same tactics.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .game_engine import EventType, GameState, Role, get_visible_events
from .logic_audit import audit
from .public_signals import build_signals
from .strategy_library import StrategyCard, StrategyLibrary, StrategyMatch
from .vote_analysis import (
    consensus_defectors,
    format_vote_analysis,
    same_vote_blocks,
    vote_history,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIBRARY_ROOT = PROJECT_ROOT / "strategy_library"

# A finding kind maps to the tactic vocabulary a human reviewer would use.
FINDING_SIGNALS: dict[str, tuple[str, ...]] = {
    "impossible_identity": ("身份泄露", "未发言", "神职"),
    "role_flip": ("身份矛盾", "前后矛盾"),
    "impossible_seer_checks": ("查验数", "一晚两验", "硬规则"),
    "one_night_two_checks": ("一晚两验", "硬规则"),
    "report_vs_vote": ("金水", "反投", "前后矛盾"),
    "vote_dead_target": ("票死人", "出局"),
    "speech_vote_mismatch": ("言行不一", "投票"),
    "living_dead_claim": ("活人说死", "出局"),
}

# When the board carries no strong signal, fall back to the cautious tactic
# for that role/phase instead of alphabetical order.
DEFAULT_TACTICS: dict[tuple[str, str], str] = {
    ("seer", "NIGHT_SEER_CHECK"): "seer.check-unverified",
    ("werewolf", "DAY_DISCUSSION"): "wolf.no-unspoken-identity",
    ("witch", "NIGHT_WITCH_ACTION"): "witch.hold-poison-without-evidence",
    ("villager", "DAY_DISCUSSION"): "villager.preserve-evidence",
    ("villager", "VOTE"): "villager.avoid-blind-bandwagon",
    ("hunter", "DAY_HUNTER_SHOT"): "good.avoid-random-hunter-shot",
}


@dataclass(frozen=True, slots=True)
class RetrievalContext:
    role: str
    phase: str
    signals: tuple[str, ...]
    text: str


def _seat_of(state: GameState, player_id: str | None) -> str:
    if not player_id:
        return "?"
    for player in state.players:
        if player.player_id == player_id:
            return str(player.seat)
    return "?"


def _public_speech_lines(state: GameState, actor, limit: int = 6) -> list[str]:
    lines: list[str] = []
    for event in get_visible_events(state, actor):
        if event.event_type not in {
            EventType.PUBLIC_SPEECH,
            EventType.LAST_WORDS,
        }:
            continue
        content = event.data.get("content")
        if event.actor_id and isinstance(content, str) and content.strip():
            lines.append(f"{_seat_of(state, event.actor_id)} 号：{content}")
    return lines[-limit:]


def build_context(state: GameState, actor) -> RetrievalContext:
    """Collect the public board signals that should drive retrieval."""

    signals: list[str] = []
    findings = audit(state, actor)
    for finding in findings:
        signals.extend(FINDING_SIGNALS.get(finding.kind, ()))

    try:
        public = build_signals(state, actor)
    except Exception:
        public = None
    if public is not None:
        seer_claimants = public.claimed_seats(frozenset({"seer"}))
        if seer_claimants:
            signals.extend(("预言家", "自报", "神职"))
        if len(seer_claimants) >= 2:
            signals.extend(("对跳", "冲突", "查验"))
        if public.reported_wolves():
            signals.extend(("查杀", "归票", "查验", "冲突"))
        if public.accusations:
            signals.append("归票")

    history = vote_history(state, actor)
    if same_vote_blocks(history):
        signals.extend(("同票", "绑票", "票型"))
    if consensus_defectors(history):
        signals.extend(("未跟最高票", "票型"))

    if actor.role is Role.WITCH:
        if state.antidote_available:
            signals.append("解药")
        if state.poison_available:
            signals.append("毒药")
    if actor.role is Role.HUNTER:
        signals.extend(("猎人", "开枪"))
    if actor.role is Role.WEREWOLF:
        signals.extend(("刀口", "悍跳"))
    if actor.role is Role.SEER:
        checked = [
            event
            for event in get_visible_events(state, actor)
            if event.event_type is EventType.SEER_CHECKED
        ]
        if checked:
            signals.extend(("未查验", "重复查验", "信息"))

    lines = _public_speech_lines(state, actor)
    lines.extend(finding.detail for finding in findings[-3:])
    votes = format_vote_analysis(state, actor)
    if votes:
        lines.append(votes)
    return RetrievalContext(
        role=actor.role.value,
        phase=state.phase.value,
        signals=tuple(dict.fromkeys(signals)),
        text="\n".join(lines),
    )


def _tokens(value: str) -> set[str]:
    lowered = value.lower()
    tokens = set(re.findall(r"[a-z0-9_]{2,}", lowered))
    for sequence in re.findall(r"[\u4e00-\u9fff]+", lowered):
        tokens.add(sequence)
        if len(sequence) > 1:
            tokens.update(
                sequence[index : index + 2]
                for index in range(len(sequence) - 1)
            )
    return tokens


def _candidates(
    library: StrategyLibrary,
    role: str,
    phase: str,
) -> list[StrategyCard]:
    cards = [
        card
        for status in ("seed", "validated")
        for card in library.load(status)
    ]
    return [
        card
        for card in cards
        if card.role == role and card.phase in {"ANY", phase}
    ]


def rank_tactics(
    state: GameState,
    actor,
    *,
    root: Path | None = None,
    limit: int = 3,
) -> list[StrategyMatch]:
    """Rank candidate tactics by structure first, then lexical overlap."""

    if limit <= 0:
        raise ValueError("limit 必须大于 0")
    library = StrategyLibrary(root or DEFAULT_LIBRARY_ROOT)
    context = build_context(state, actor)
    cards = _candidates(library, context.role, context.phase)
    query_tokens = _tokens(context.text)
    signal_tokens = {
        token for signal in context.signals for token in _tokens(signal)
    }
    ranked: list[StrategyMatch] = []
    for card in cards:
        card_tokens = _tokens(card.searchable_text)
        score = 0.0
        if card.phase == context.phase:
            score += 6.0
        elif card.phase == "ANY":
            score += 2.0
        score += 5.0 * len(signal_tokens & card_tokens)
        score += 1.0 * len(query_tokens & card_tokens)
        if DEFAULT_TACTICS.get((context.role, context.phase)) == card.strategy_id:
            score += 4.0
        if card.status == "validated":
            score += 1.0
        if card.evidence_level == "human_validated":
            score += 2.0
        matched = sorted((query_tokens | signal_tokens) & card_tokens)
        ranked.append(
            StrategyMatch(card=card, score=score, matched_terms=matched)
        )
    ranked.sort(key=lambda item: (-item.score, item.card.strategy_id))
    return ranked[:limit]


__all__ = [
    "FINDING_SIGNALS",
    "RetrievalContext",
    "build_context",
    "rank_tactics",
]
