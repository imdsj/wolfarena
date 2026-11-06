"""A closed set of decision directives a validated tactic may carry.

Free-text tactics cannot be executed safely. Every promoted card may carry
exactly one directive from this allow-list, and each one only reshuffles the
server-provided legal targets. A directive can never invent an action or a
target: if its preferred seat is not in ``view.target_ids`` the policy falls
back to the L1 rule choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .game_engine import GameState, Player
from .public_signals import PublicSignals, build_signals


Directive = Literal[
    "vote_most_accused",
    "vote_reported_wolf",
    "vote_silent",
    "witch_poison_most_accused",
    "witch_save_only_god",
    "hunter_shoot_most_accused",
    "hunter_hold",
    "seer_check_counterclaim",
    "wolf_kill_accuser",
]

DIRECTIVES: tuple[str, ...] = (
    "vote_most_accused",
    "vote_reported_wolf",
    "vote_silent",
    "witch_poison_most_accused",
    "witch_save_only_god",
    "hunter_shoot_most_accused",
    "hunter_hold",
    "seer_check_counterclaim",
    "wolf_kill_accuser",
)

DIRECTIVE_ACTIONS: dict[str, frozenset[str]] = {
    "vote_most_accused": frozenset({"vote"}),
    "vote_reported_wolf": frozenset({"vote"}),
    "vote_silent": frozenset({"vote"}),
    "witch_poison_most_accused": frozenset({"witch_action"}),
    "witch_save_only_god": frozenset({"witch_action"}),
    "hunter_shoot_most_accused": frozenset(
        {"night_hunter_shot", "day_hunter_shot"}
    ),
    "hunter_hold": frozenset({"night_hunter_shot", "day_hunter_shot"}),
    "seer_check_counterclaim": frozenset({"seer_check"}),
    "wolf_kill_accuser": frozenset({"wolf_kill"}),
}

GOD_ROLES = frozenset({"seer", "witch", "hunter"})


@dataclass(frozen=True, slots=True)
class DirectiveDecision:
    """A directive's preferred target/choice, still subject to validation."""

    target_id: str | None = None
    choice: str | None = None


def _seat_map(state: GameState) -> dict[str, int]:
    return {player.player_id: player.seat for player in state.players}


def _by_seat(
    state: GameState,
    view,
    seat: int | None,
) -> str | None:
    if seat is None:
        return None
    for player_id, player_seat in _seat_map(state).items():
        if player_seat == seat and player_id in view.target_ids:
            return player_id
    return None


def _signals(state: GameState, actor: Player) -> PublicSignals:
    return build_signals(state, actor)


def _vote_most_accused(state, actor, view, signals) -> DirectiveDecision | None:
    seat = signals.top_accused(exclude=actor.seat)
    target = _by_seat(state, view, seat)
    return DirectiveDecision(target_id=target) if target else None


def _vote_reported_wolf(state, actor, view, signals) -> DirectiveDecision | None:
    reported = signals.reported_wolves()
    for seat in reversed(reported):
        target = _by_seat(state, view, seat)
        if target:
            return DirectiveDecision(target_id=target)
    return None


def _vote_silent(state, actor, view, signals) -> DirectiveDecision | None:
    for player_id, seat in _seat_map(state).items():
        if player_id not in view.target_ids or seat == actor.seat:
            continue
        if seat not in signals.spoken_seats:
            return DirectiveDecision(target_id=player_id)
    return None


def _witch_poison_most_accused(
    state,
    actor,
    view,
    signals,
) -> DirectiveDecision | None:
    seat = signals.top_accused(exclude=actor.seat, minimum=2)
    target = _by_seat(state, view, seat)
    if target and "poison" in view.choices:
        return DirectiveDecision(target_id=target, choice="poison")
    return None


def _witch_save_only_god(
    state,
    actor,
    view,
    signals,
) -> DirectiveDecision | None:
    if "antidote" not in view.choices or "none" not in view.choices:
        return None
    night_result = state.night_result
    victim = night_result.wolf_target_id if night_result is not None else None
    if victim is None or victim not in view.target_ids:
        return DirectiveDecision(choice="none")
    victim_seat = _seat_map(state).get(victim)
    gods = signals.claimed_seats(GOD_ROLES)
    if victim_seat in gods:
        return DirectiveDecision(target_id=victim, choice="antidote")
    return DirectiveDecision(choice="none")


def _hunter_shoot_most_accused(
    state,
    actor,
    view,
    signals,
) -> DirectiveDecision | None:
    seat = signals.top_accused(exclude=actor.seat, minimum=2)
    target = _by_seat(state, view, seat)
    if target:
        return DirectiveDecision(target_id=target)
    return DirectiveDecision()


def _hunter_hold(state, actor, view, signals) -> DirectiveDecision:
    return DirectiveDecision()


def _seer_check_counterclaim(
    state,
    actor,
    view,
    signals,
) -> DirectiveDecision | None:
    claimants = signals.claimed_seats(frozenset({"seer"}))
    claimants.discard(actor.seat)
    for seat in sorted(claimants):
        target = _by_seat(state, view, seat)
        if target:
            return DirectiveDecision(target_id=target)
    return None


def _wolf_kill_accuser(state, actor, view, signals) -> DirectiveDecision | None:
    seat = signals.top_accused(exclude=actor.seat)
    target = _by_seat(state, view, seat)
    return DirectiveDecision(target_id=target) if target else None


HANDLERS = {
    "vote_most_accused": _vote_most_accused,
    "vote_reported_wolf": _vote_reported_wolf,
    "vote_silent": _vote_silent,
    "witch_poison_most_accused": _witch_poison_most_accused,
    "witch_save_only_god": _witch_save_only_god,
    "hunter_shoot_most_accused": _hunter_shoot_most_accused,
    "hunter_hold": _hunter_hold,
    "seer_check_counterclaim": _seer_check_counterclaim,
    "wolf_kill_accuser": _wolf_kill_accuser,
}


def directive_applies(directive: str, action: str) -> bool:
    return action in DIRECTIVE_ACTIONS.get(directive, frozenset())


def apply_directive(
    directive: str,
    state: GameState,
    actor: Player,
    view,
) -> DirectiveDecision | None:
    """Return the directive's preferred move, or None when it has no opinion."""

    handler = HANDLERS.get(directive)
    if handler is None or not directive_applies(directive, view.action):
        return None
    signals = _signals(state, actor)
    decision = handler(state, actor, view, signals)
    if decision is None:
        return None
    if decision.target_id is not None and decision.target_id not in view.target_ids:
        return None
    if decision.choice is not None and decision.choice not in view.choices:
        return None
    return decision
