"""One independent decision-making agent per AI seat.

Each agent owns its persona, its deterministic policy and its decision trace.
The trace is the structured, spectator-visible record of what the agent chose
and which tools/evidence it used, not a raw model chain-of-thought.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .game_engine import GameState, Role
from .personas import Archetype, ArchetypePolicy, assign_archetypes
from .strategy_library import StrategyCard


@dataclass(slots=True)
class DecisionTrace:
    """One auditable, spectator-visible decision made by an agent."""

    day: int
    phase: str
    action: str
    target_id: str | None
    choice: str | None
    persona: str
    strategy_id: str
    rationale: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    evidence_event_ids: list[int] = field(default_factory=list)
    tactic_ids: list[str] = field(default_factory=list)
    content: str | None = None

    def as_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "action": self.action,
            "target_id": self.target_id,
            "choice": self.choice,
            "persona": self.persona,
            "strategy_id": self.strategy_id,
            "rationale": self.rationale,
            "tool_calls": list(self.tool_calls),
            "evidence_event_ids": list(self.evidence_event_ids),
            "tactic_ids": list(self.tactic_ids),
            "content": self.content,
        }


@dataclass(slots=True)
class PlayerAgent:
    """A seat's independent persona, policy and decision history."""

    player_id: str
    persona: Archetype
    policy: ArchetypePolicy
    decision_traces: list[DecisionTrace] = field(default_factory=list)
    current_plan: str | None = None

    def record(
        self,
        *,
        day: int,
        phase: str,
        action: str,
        target_id: str | None,
        choice: str | None,
        strategy_id: str,
        rationale: str | None = None,
        tool_calls: list[dict] | None = None,
        evidence_event_ids: list[int] | None = None,
        tactic_ids: list[str] | None = None,
        content: str | None = None,
    ) -> None:
        tools = [
            str(call.get("name"))
            for call in (tool_calls or ())
            if isinstance(call, dict) and call.get("name")
        ]
        basis: list[str] = []
        if tools:
            basis.append("调用工具 " + "、".join(tools))
        if tactic_ids:
            basis.append("命中战术 " + "、".join(tactic_ids))
        if not basis:
            basis.append(f"按{self.persona.value}人格规则评估合法动作")
        rationale = "；".join(basis)
        if content:
            rationale += "；已形成具体发言/分工"
        self.current_plan = (
            f"第{day}天 {phase}：{rationale}，"
            f"拟执行 {action}"
            + (f" → {target_id}" if target_id else "")
        )
        self.decision_traces.append(
            DecisionTrace(
                day=day,
                phase=phase,
                action=action,
                target_id=target_id,
                choice=choice,
                persona=self.persona.value,
                strategy_id=strategy_id,
                rationale=rationale,
                tool_calls=list(tool_calls or ()),
                evidence_event_ids=list(evidence_event_ids or ()),
                tactic_ids=list(tactic_ids or ()),
                content=content,
            )
        )


def build_agents(
    state: GameState,
    cards: tuple[StrategyCard, ...],
) -> dict[str, PlayerAgent]:
    """Create one agent per non-human seat with a stable archetype."""

    archetypes = assign_archetypes(state.seed, state.players)
    agents: dict[str, PlayerAgent] = {}
    for player in state.players:
        if player.is_human:
            continue
        archetype = archetypes[player.player_id]
        agents[player.player_id] = PlayerAgent(
            player_id=player.player_id,
            persona=archetype,
            policy=ArchetypePolicy(
                seed=state.seed,
                archetype=archetype,
                cards=cards,
            ),
        )
    return agents


__all__ = [
    "Archetype",
    "DecisionTrace",
    "PlayerAgent",
    "Role",
    "build_agents",
]
