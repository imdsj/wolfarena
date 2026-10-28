"""Minimal terminal-reward Q-learning policy (``l2.qtable.v1``).

Scope of this first version:

- State: the agent's own role, phase, day bucket and public alive count.
- Action: the server-approved action type only.
- Target/choice/content: delegated to the L1 rule policy.
- Reward: +1 for the agent's faction winning, -1 for losing, 0 otherwise.
- Training and evaluation seeds must not overlap.

The policy never inspects another player's role, and it never invents an
action outside ``legal_actions``. Seeds and configuration are stored with the
table so a run can be reproduced and audited.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from random import Random
from typing import Any, Sequence

from .ai_growth import L1RulePolicy
from .game_engine import GameState, Role


STRATEGY_ID = "l2.qtable.v1"
MODEL_SCHEMA_VERSION = 1

# Tie-breaking order at zero value, inherited from the L1 rule policy.
ACTION_PRIORITY: tuple[str, ...] = (
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
_PRIORITY_INDEX = {action: index for index, action in enumerate(ACTION_PRIORITY)}


def day_bucket(day: int) -> str:
    """Coarse day bucket so the table stays small and reusable."""

    if day <= 1:
        return "d1"
    if day <= 3:
        return "d2-3"
    return "d4+"


def alive_bucket(alive: int) -> str:
    """Coarse public alive-count bucket."""

    if alive >= 9:
        return "a9"
    if alive >= 7:
        return "a7-8"
    if alive >= 5:
        return "a5-6"
    if alive >= 3:
        return "a3-4"
    return "a0-2"


def state_key(*, role: str, phase: str, day: int, alive: int) -> str:
    """Discrete key built exclusively from the agent's own visible state."""

    return "|".join(
        (role, phase, day_bucket(day), alive_bucket(alive))
    )


def visible_key(state: GameState, actor) -> str:
    """Derive a state key without reading any hidden player identity."""

    alive = sum(1 for player in state.players if player.is_alive)
    return state_key(
        role=actor.role.value,
        phase=state.phase.value,
        day=state.day,
        alive=alive,
    )


def faction_of(role: Role | str) -> str:
    value = role.value if isinstance(role, Role) else str(role)
    return "wolf" if value == Role.WEREWOLF.value else "good"


@dataclass(slots=True)
class QPolicyConfig:
    """Hyper-parameters recorded in the model file."""

    seed: int
    epsilon_start: float = 0.3
    epsilon_end: float = 0.05
    alpha: float = 0.2
    gamma: float = 0.95
    training: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数")
        if not 0.0 <= self.epsilon_end <= self.epsilon_start <= 1.0:
            raise ValueError("epsilon 必须满足 0 <= end <= start <= 1")
        if not 0.0 < self.alpha <= 1.0:
            raise ValueError("alpha 必须在 (0, 1] 内")
        if not 0.0 <= self.gamma <= 1.0:
            raise ValueError("gamma 必须在 [0, 1] 内")

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "epsilon_start": self.epsilon_start,
            "epsilon_end": self.epsilon_end,
            "alpha": self.alpha,
            "gamma": self.gamma,
            "training": self.training,
        }


@dataclass(slots=True)
class _Pending:
    key: str
    action: str
    faction: str


class QTablePolicy:
    """Epsilon-greedy tabular learner over action types."""

    strategy_id: str = STRATEGY_ID
    stage_name: str = "L2_STRATEGY"

    def __init__(
        self,
        config: QPolicyConfig,
        *,
        q_table: dict[str, dict[str, float]] | None = None,
        stats: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.q_table: dict[str, dict[str, float]] = {
            key: dict(values) for key, values in (q_table or {}).items()
        }
        self.stats: dict[str, Any] = {
            "episodes": 0,
            "updates": 0,
            "decisions": 0,
            **(stats or {}),
        }
        self.meta: dict[str, Any] = dict(meta or {})
        self._rng = Random(config.seed)
        self._rules = L1RulePolicy(seed=config.seed)
        self._pending: dict[str, _Pending] = {}
        self._current_key: str | None = None
        self._current_role: Role | None = None
        self._active_actor_id: str | None = None
        self._progress = 0.0

    # -- training loop hooks ------------------------------------------------

    @property
    def epsilon(self) -> float:
        start = self.config.epsilon_start
        end = self.config.epsilon_end
        if not self.config.training:
            return 0.0
        progress = min(max(self._progress, 0.0), 1.0)
        return start + (end - start) * progress

    def set_progress(self, completed: int, total: int) -> None:
        if total <= 0:
            raise ValueError("total 必须大于 0")
        self._progress = min(max(completed / total, 0.0), 1.0)

    def freeze(self) -> str:
        """Switch to greedy evaluation and return the pre-freeze hash."""

        digest = self.content_hash
        self.config.training = False
        self.stats = {"episodes": 0, "updates": 0, "decisions": 0}
        self.meta["frozen_from_hash"] = digest
        return digest

    def begin_episode(self) -> None:
        self._pending.clear()
        self._current_key = None
        self._current_role = None
        self._active_actor_id = None

    def end_episode(self, winner: str | None) -> None:
        """Apply the terminal reward once the game result is known."""

        for pending in self._pending.values():
            reward = 0.0
            if winner is not None:
                reward = 1.0 if pending.faction == winner else -1.0
            self._update(pending.key, pending.action, reward, None)
        self._pending.clear()
        self.stats["episodes"] = int(self.stats.get("episodes", 0)) + 1

    # -- policy interface used by AIController ------------------------------

    def observe_state(self, state: GameState, actor) -> None:
        """Record the acting agent's visible state before it chooses."""

        self._current_key = visible_key(state, actor)
        self._current_role = actor.role
        self._active_actor_id = actor.player_id

    def choose_action(self, legal_actions: Sequence[str]) -> str:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("没有合法动作可供选择")
        if any(not isinstance(action, str) or not action for action in actions):
            raise ValueError("每个合法动作必须是非空字符串")
        if len(set(actions)) != len(actions):
            raise ValueError("合法动作不能重复")

        key = self._current_key
        if key is None:
            raise RuntimeError("Q 策略必须先绑定可见状态再选择动作")

        if self.config.training and self._rng.random() < self.epsilon:
            chosen = self._rng.choice(actions)
        else:
            values = self.q_table.get(key, {})
            chosen = max(
                actions,
                key=lambda action: (
                    values.get(action, 0.0),
                    -_PRIORITY_INDEX.get(action, len(ACTION_PRIORITY)),
                ),
            )
        if chosen not in actions:
            raise RuntimeError("Q 策略选择了不在 legal_actions 中的动作")

        self._track(key, chosen)
        return chosen

    def choose_choice(self, state: GameState, actor, view) -> str | None:
        return self._rules.choose_choice(state, actor, view)

    def choose_target(
        self,
        state: GameState,
        actor,
        view,
        *,
        choice: str | None,
    ) -> str | None:
        return self._rules.choose_target(
            state, actor, view, choice=choice
        )

    @staticmethod
    def choose_content(actor, view) -> str | None:
        return L1RulePolicy.choose_content(actor, view)

    # -- learning -----------------------------------------------------------

    def _track(self, key: str, action: str) -> None:
        self.stats["decisions"] = int(self.stats.get("decisions", 0)) + 1
        if not self.config.training:
            return
        role = self._current_role
        if role is None:
            return
        actor_id = self._active_actor_id
        if actor_id is None:
            return
        previous = self._pending.get(actor_id)
        if previous is not None:
            # Intermediate steps carry no reward in this version.
            self._update(previous.key, previous.action, 0.0, key)
        self._pending[actor_id] = _Pending(
            key=key, action=action, faction=faction_of(role)
        )

    def _update(
        self,
        key: str,
        action: str,
        reward: float,
        next_key: str | None,
    ) -> None:
        if not self.config.training:
            return
        values = self.q_table.setdefault(key, {})
        current = values.get(action, 0.0)
        bootstrap = 0.0
        if next_key is not None:
            next_values = self.q_table.get(next_key)
            if next_values:
                bootstrap = max(next_values.values())
        target = reward + self.config.gamma * bootstrap
        values[action] = round(
            current + self.config.alpha * (target - current), 9
        )
        self.stats["updates"] = int(self.stats.get("updates", 0)) + 1

    # -- persistence --------------------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        table = {
            key: {action: values[action] for action in sorted(values)}
            for key, values in sorted(self.q_table.items())
        }
        core = {
            "strategy_id": self.strategy_id,
            "config": self.config.as_dict(),
            "q_table": table,
        }
        digest = hashlib.sha256(
            json.dumps(core, ensure_ascii=False, sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest()
        return {
            "schema_version": MODEL_SCHEMA_VERSION,
            **core,
            "stats": {
                "episodes": int(self.stats.get("episodes", 0)),
                "updates": int(self.stats.get("updates", 0)),
                "decisions": int(self.stats.get("decisions", 0)),
                "states": len(table),
                "state_action_pairs": sum(len(v) for v in table.values()),
            },
            "meta": dict(self.meta),
            "content_hash": digest,
        }

    @property
    def content_hash(self) -> str:
        return self.to_payload()["content_hash"]

    def save(self, path: Path) -> str:
        payload = self.to_payload()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload["content_hash"]

    @classmethod
    def load(cls, path: Path) -> "QTablePolicy":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != MODEL_SCHEMA_VERSION:
            raise ValueError("不支持的模型 schema 版本")
        if payload.get("strategy_id") != STRATEGY_ID:
            raise ValueError("模型 strategy_id 不匹配")
        config = QPolicyConfig(**payload["config"])
        policy = cls(
            config,
            q_table=payload.get("q_table", {}),
            stats=payload.get("stats", {}),
            meta=payload.get("meta", {}),
        )
        if policy.content_hash != payload.get("content_hash"):
            raise ValueError("模型内容哈希不匹配，文件可能被修改")
        return policy
