"""Four deterministic player archetypes that only bias legal choices.

An archetype never invents an action or a target: it reorders the targets the
server already declared legal. Validated tactic directives still take
precedence, so a promoted tactic behaves identically across archetypes and
self-play stays reproducible.
"""

from __future__ import annotations

from enum import Enum
from random import Random

from .ai_growth import L1RulePolicy
from .directives import apply_directive
from .game_engine import EventType, GameState, Role, get_visible_events
from .strategy_library import StrategyCard
from .tactic_policy import DirectivePolicy


class Archetype(str, Enum):
    """The stable identity of one AI seat."""

    AGGRESSIVE = "aggressive"
    STEADY = "steady"
    LOGICAL = "logical"
    CHAOTIC = "chaotic"


ARCHETYPE_ORDER: tuple[Archetype, ...] = (
    Archetype.AGGRESSIVE,
    Archetype.STEADY,
    Archetype.LOGICAL,
    Archetype.CHAOTIC,
)

ARCHETYPE_LABELS: dict[Archetype, str] = {
    Archetype.AGGRESSIVE: "冲锋型",
    Archetype.STEADY: "稳健型",
    Archetype.LOGICAL: "逻辑型",
    Archetype.CHAOTIC: "搅局型",
}


def assign_archetypes(seed: int, players) -> dict[str, Archetype]:
    """Stable assignment; wolves always receive distinct, complementary types."""

    wolves = sorted(
        (player for player in players if player.role is Role.WEREWOLF),
        key=lambda player: player.seat,
    )
    wolf_by_id = {
        wolf.player_id: ARCHETYPE_ORDER[
            (seed + index) % len(ARCHETYPE_ORDER)
        ]
        for index, wolf in enumerate(wolves)
    }
    assigned: dict[str, Archetype] = {}
    for player in players:
        if player.role is Role.WEREWOLF:
            assigned[player.player_id] = wolf_by_id[player.player_id]
        else:
            assigned[player.player_id] = ARCHETYPE_ORDER[
                (seed + player.seat) % len(ARCHETYPE_ORDER)
            ]
    return assigned


class ArchetypePolicy(DirectivePolicy):
    """Validated tactics first, then an archetype bias over legal targets."""

    def __init__(
        self,
        *,
        seed: int,
        archetype: Archetype,
        cards: tuple[StrategyCard, ...] = (),
    ) -> None:
        super().__init__(seed=seed, cards=cards)
        self.archetype = archetype
        self.strategy_id = f"l1.persona.{archetype.value}"
        if self.cards:
            self.strategy_id += "+tactics"

    def choose_target(self, state, actor, view, *, choice: str | None = None):
        for card in self._matching(state, actor, view.action):
            decision = apply_directive(card.directive, state, actor, view)
            if decision is not None:
                return decision.target_id
        persona_target = self._persona_target(state, actor, view, choice)
        if persona_target is not None:
            return persona_target
        return super().choose_target(state, actor, view, choice=choice)

    def _persona_target(self, state, actor, view, choice: str | None):
        if not view.target_ids:
            return None
        if view.action not in {
            "vote",
            "wolf_kill",
            "seer_check",
            "night_hunter_shot",
            "day_hunter_shot",
        }:
            return None

        candidates = list(view.target_ids)
        if view.action == "wolf_kill":
            candidates = [
                target_id
                for target_id in candidates
                if not self._is_wolf(state, target_id)
            ] or candidates

        if self.archetype is Archetype.CHAOTIC:
            rng = Random(
                f"{self.seed}:{actor.player_id}:{state.day}:{state.phase.value}"
            )
            picks = [
                target_id
                for target_id in candidates
                if target_id != actor.player_id
            ] or candidates
            return rng.choice(picks)

        from .public_signals import build_signals

        try:
            signals = build_signals(state, actor)
        except Exception:
            signals = None

        if self.archetype is Archetype.LOGICAL:
            from .logic_audit import top_suspect

            try:
                seat = top_suspect(state, actor, exclude=actor.seat)
            except Exception:
                seat = None
            if seat is not None:
                target = self._by_seat(state, view, seat, candidates)
                if target and target != actor.player_id:
                    return target

        if signals is not None and self.archetype is Archetype.AGGRESSIVE:
            for seat in reversed(signals.reported_wolves()):
                target = self._by_seat(state, view, seat, candidates)
                if target and target != actor.player_id:
                    return target
            seat = signals.top_accused(exclude=actor.seat)
            if seat is not None:
                target = self._by_seat(state, view, seat, candidates)
                if target and target != actor.player_id:
                    return target

        if signals is not None and self.archetype is Archetype.STEADY:
            seat = signals.top_accused(exclude=actor.seat, minimum=2)
            if seat is not None:
                target = self._by_seat(state, view, seat, candidates)
                if target and target != actor.player_id:
                    return target

        if signals is not None and self.archetype is Archetype.LOGICAL:
            seat = signals.top_accused(exclude=actor.seat)
            if seat is not None:
                target = self._by_seat(state, view, seat, candidates)
                if target and target != actor.player_id:
                    return target

        return None

    @staticmethod
    def _is_wolf(state: GameState, player_id: str) -> bool:
        return any(
            player.player_id == player_id and player.role is Role.WEREWOLF
            for player in state.players
        )

    @staticmethod
    def _by_seat(
        state: GameState,
        view,
        seat: int | None,
        candidates: list[str],
    ) -> str | None:
        if seat is None:
            return None
        for player in state.players:
            if (
                player.seat == seat
                and player.player_id in view.target_ids
                and player.player_id in candidates
            ):
                return player.player_id
        return None


def persona_guidance(archetype: Archetype | None) -> str:
    """A short speech-style hint for the LLM, empty for unknown personas."""

    if archetype is None:
        return ""
    guidance = {
        Archetype.AGGRESSIVE: "你偏好高风险打法：早跳身份、敢定票、优先归最可疑的人。",
        Archetype.STEADY: "你偏好稳健打法：少出头、跟最强证据、避免分票，证据不足不冒险。",
        Archetype.LOGICAL: "你偏好逻辑打法：优先抓硬规则矛盾、票型和查验链，按证据归票。",
        Archetype.CHAOTIC: "你偏好施压打法：多线质疑、逼别人发言、打乱节奏，不按常理出牌。",
    }
    return guidance[archetype]


__all__ = [
    "ARCHETYPE_LABELS",
    "ARCHETYPE_ORDER",
    "Archetype",
    "ArchetypePolicy",
    "L1RulePolicy",
    "assign_archetypes",
    "persona_guidance",
]
