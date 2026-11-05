"""L1 plus every validated tactic directive the library currently holds."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .ai_growth import L1RulePolicy
from .directives import apply_directive, directive_applies
from .strategy_library import StrategyCard, StrategyLibrary

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIBRARY_ROOT = PROJECT_ROOT / "strategy_library"


def load_validated_directives(
    root: Path | None = None,
) -> tuple[StrategyCard, ...]:
    """Validated cards with an executable directive, sorted for determinism."""

    library = StrategyLibrary(root or DEFAULT_LIBRARY_ROOT)
    cards = [
        card
        for card in library.load("validated")
        if card.directive and directive_applies(card.directive, card.action)
    ]
    cards.sort(key=lambda card: card.strategy_id)
    return tuple(cards)


class DirectivePolicy(L1RulePolicy):
    """A deterministic policy that consults validated tactics first.

    It never calls a model, so 200-game evaluations stay free and reproducible.
    """

    def __init__(
        self,
        *,
        seed: int,
        cards: Sequence[StrategyCard] = (),
    ) -> None:
        super().__init__(seed=seed)
        self.cards = tuple(
            card
            for card in cards
            if card.directive and directive_applies(card.directive, card.action)
        )
        self.strategy_id = (
            "l1.rule.v1+tactics" if self.cards else "l1.rule.v1"
        )

    def _matching(self, state, actor, action: str) -> list[StrategyCard]:
        return [
            card
            for card in self.cards
            if card.role == actor.role.value
            and card.action == action
            and card.phase in {"ANY", state.phase.value}
        ]

    def choose_choice(self, state, actor, view) -> str | None:
        for card in self._matching(state, actor, view.action):
            decision = apply_directive(card.directive, state, actor, view)
            if decision is not None:
                return decision.choice
        return super().choose_choice(state, actor, view)

    def choose_target(self, state, actor, view, *, choice: str | None = None):
        for card in self._matching(state, actor, view.action):
            decision = apply_directive(card.directive, state, actor, view)
            if decision is not None:
                return decision.target_id
        return super().choose_target(state, actor, view, choice=choice)
