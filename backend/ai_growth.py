"""Auditable AI growth records and the non-LLM L0 policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from random import Random
from typing import Final, Sequence

from .game_engine import (
    EventType,
    GameState,
    Phase,
    Role,
    get_visible_events,
)


class GrowthStage(str, Enum):
    """Stable growth stages shared by the backend and frontend."""

    L0_NOVICE = "L0_NOVICE"
    L1_RULE = "L1_RULE"
    L2_STRATEGY = "L2_STRATEGY"
    L3_ADVERSARIAL = "L3_ADVERSARIAL"


GROWTH_STAGE_ORDER: Final[tuple[GrowthStage, ...]] = (
    GrowthStage.L0_NOVICE,
    GrowthStage.L1_RULE,
    GrowthStage.L2_STRATEGY,
    GrowthStage.L3_ADVERSARIAL,
)


@dataclass(slots=True)
class DecisionRecord:
    """One auditable action choice made by a player or agent."""

    game_id: str
    seed: int
    day: int
    phase: Phase
    player_id: str
    role: Role
    legal_actions: tuple[str, ...]
    chosen_action: str
    strategy_id: str
    confidence: float
    outcome: str | None = None
    reflection: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.game_id, str) or not self.game_id.strip():
            raise ValueError("game_id 必须是非空字符串")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数")
        if isinstance(self.day, bool) or not isinstance(self.day, int):
            raise ValueError("day 必须是整数")
        if self.day < 0:
            raise ValueError("day 不能小于 0")
        if not isinstance(self.phase, Phase):
            raise ValueError("phase 必须是 Phase")
        if not isinstance(self.player_id, str) or not self.player_id.strip():
            raise ValueError("player_id 必须是非空字符串")
        if not isinstance(self.role, Role):
            raise ValueError("role 必须是 Role")

        legal_actions = tuple(self.legal_actions)
        if not legal_actions:
            raise ValueError("legal_actions 不能为空")
        if any(
            not isinstance(action, str) or not action.strip()
            for action in legal_actions
        ):
            raise ValueError("每个合法动作必须是非空字符串")
        if len(set(legal_actions)) != len(legal_actions):
            raise ValueError("legal_actions 不能包含重复动作")
        if (
            not isinstance(self.chosen_action, str)
            or self.chosen_action not in legal_actions
        ):
            raise ValueError("chosen_action 必须来自 legal_actions")
        if not isinstance(self.strategy_id, str) or not self.strategy_id.strip():
            raise ValueError("strategy_id 必须是非空字符串")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence 必须在 0 到 1 之间")

        self.legal_actions = legal_actions
        self.confidence = float(self.confidence)
        self.outcome = self.outcome.strip() if self.outcome else None
        self.reflection = self.reflection.strip() if self.reflection else None


@dataclass(slots=True)
class StrategyRecord:
    """A strategy entry whose metrics remain unknown until real samples exist."""

    strategy_id: str
    role: Role
    phase: Phase
    trigger: str
    action: str
    source: str
    samples: int = 0
    win_rate: float | None = None
    interval: tuple[float, float] | None = None
    version: str = "v0.1"
    status: str = "untested"

    def __post_init__(self) -> None:
        for field_name in (
            "strategy_id",
            "trigger",
            "action",
            "source",
            "version",
            "status",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须是非空字符串")
        if not isinstance(self.role, Role):
            raise ValueError("role 必须是 Role")
        if not isinstance(self.phase, Phase):
            raise ValueError("phase 必须是 Phase")
        if (
            isinstance(self.samples, bool)
            or not isinstance(self.samples, int)
            or self.samples < 0
        ):
            raise ValueError("samples 必须是大于等于 0 的整数")

        if self.win_rate is not None:
            if (
                isinstance(self.win_rate, bool)
                or not isinstance(self.win_rate, (int, float))
                or not 0 <= self.win_rate <= 1
            ):
                raise ValueError("win_rate 必须在 0 到 1 之间")
            self.win_rate = float(self.win_rate)
            if self.samples == 0:
                raise ValueError("没有真实样本时不能填写 win_rate")

        if self.interval is not None:
            if (
                not isinstance(self.interval, tuple)
                or len(self.interval) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= value <= 1
                    for value in self.interval
                )
                or self.interval[0] > self.interval[1]
            ):
                raise ValueError("interval 必须是 0 到 1 之间的有序二元组")
            self.interval = (float(self.interval[0]), float(self.interval[1]))
            if self.win_rate is None or self.samples == 0:
                raise ValueError("没有真实胜率和样本时不能填写 interval")


@dataclass(slots=True)
class L0Policy:
    """A deterministic random policy that only selects server-approved actions."""

    seed: int
    strategy_id: str = "l0.random.v1"
    stage: GrowthStage = GrowthStage.L0_NOVICE
    _rng: Random = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数")
        if self.stage is not GrowthStage.L0_NOVICE:
            raise ValueError("L0Policy 只能使用 L0_NOVICE 阶段")
        self._rng = Random(self.seed)

    def choose_action(self, legal_actions: Sequence[str]) -> str:
        """Choose exactly one action from a non-empty, unique action list."""

        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("没有合法动作可供选择")
        if any(
            not isinstance(action, str) or not action.strip()
            for action in actions
        ):
            raise ValueError("每个合法动作必须是非空字符串")
        if len(set(actions)) != len(actions):
            raise ValueError("合法动作不能重复")

        chosen = self._rng.choice(actions)
        if chosen not in actions:
            raise RuntimeError("L0 选择了不在 legal_actions 中的动作")
        return chosen

    def make_decision(
        self,
        *,
        game_id: str,
        day: int,
        phase: Phase,
        player_id: str,
        role: Role,
        legal_actions: Sequence[str],
    ) -> DecisionRecord:
        """Choose an action and return an auditable decision record."""

        actions = tuple(legal_actions)
        chosen = self.choose_action(actions)
        return DecisionRecord(
            game_id=game_id,
            seed=self.seed,
            day=day,
            phase=phase,
            player_id=player_id,
            role=role,
            legal_actions=actions,
            chosen_action=chosen,
            strategy_id=self.strategy_id,
            confidence=0.0,
        )


@dataclass(slots=True)
class L1RulePolicy:
    """A deterministic rule policy that uses only legal actions and views."""

    seed: int
    strategy_id: str = "l1.rule.v1"
    stage: GrowthStage = GrowthStage.L1_RULE

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数")
        if self.stage is not GrowthStage.L1_RULE:
            raise ValueError("L1RulePolicy 只能使用 L1_RULE 阶段")

    def choose_action(self, legal_actions: Sequence[str]) -> str:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("没有合法动作可供选择")
        if len(set(actions)) != len(actions):
            raise ValueError("合法动作不能重复")
        priority = (
            "wolf_speech",
            "seer_check",
            "witch_action",
            "night_hunter_shot",
            "day_hunter_shot",
            "speech",
            "last_words",
            "vote",
            "wolf_kill",
            "start_night",
            "resolve_night",
            "begin_day",
            "close_vote",
            "resolve_vote",
            "begin_banishment_last_words",
            "close_self_destruct_window",
            "self_destruct",
        )
        for action in priority:
            if action in actions:
                return action
        return actions[0]

    def choose_choice(
        self,
        state: GameState,
        actor,
        view,
    ) -> str | None:
        if not view.choices:
            return None
        if view.action == "witch_action":
            night_result = state.night_result
            if (
                "antidote" in view.choices
                and state.antidote_available
                and night_result is not None
                and night_result.wolf_target_id in view.target_ids
            ):
                return "antidote"
            if "none" in view.choices:
                return "none"
        return view.choices[0]

    def choose_target(
        self,
        state: GameState,
        actor,
        view,
        *,
        choice: str | None,
    ) -> str | None:
        if not view.target_ids:
            return None
        if view.action == "witch_action":
            if choice != "antidote":
                return None
            night_result = state.night_result
            target = (
                night_result.wolf_target_id
                if night_result is not None
                else None
            )
            return target if target in view.target_ids else None
        if view.action == "wolf_kill":
            claimed = self._claimed_god_ids(state, actor)
            return next(
                (
                    target_id
                    for target_id in view.target_ids
                    if target_id in claimed
                ),
                view.target_ids[0],
            )
        if view.action == "seer_check":
            checked = {
                event.target_id
                for event in get_visible_events(state, actor)
                if event.event_type is EventType.SEER_CHECKED
            }
            return next(
                (
                    target_id
                    for target_id in view.target_ids
                    if target_id not in checked
                ),
                view.target_ids[0],
            )
        return view.target_ids[0]

    @staticmethod
    def choose_content(actor, view) -> str | None:
        if not view.requires_content:
            return None
        if view.action == "wolf_speech":
            return f"L1规则狼{actor.seat}号发言"
        if view.action == "last_words":
            return f"L1规则{actor.seat}号遗言"
        return f"我是{actor.seat}号，先听后续发言。"

    @staticmethod
    def _claimed_god_ids(state: GameState, actor) -> set[str]:
        keywords = ("预言家", "女巫", "猎人")
        claims: set[str] = set()
        for event in get_visible_events(state, actor):
            if event.event_type not in {
                EventType.PUBLIC_SPEECH,
                EventType.LAST_WORDS,
            }:
                continue
            content = event.data.get("content")
            if (
                event.actor_id
                and isinstance(content, str)
                and any(keyword in content for keyword in keywords)
            ):
                claims.add(event.actor_id)
        return claims
