"""Candidate evaluation and promotion assistance.

This closes the experience loop: a candidate tactic is compared against a
baseline on the SAME seeds, and the result is written as promotion evidence.
Promotion still requires a human to flip ``approved`` and run the existing
``strategy_library promote`` command, so no tactic becomes searchable without
proof plus human sign-off.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from .ai_growth import L1RulePolicy
from .ai_provider import DeepSeekSettings
from .game_engine import GameState, Player
from .simulator import simulate_game
from .strategy_library import StrategyCard, StrategyLibrary
from .training import wilson_interval

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _seat(state: GameState, player_id: str) -> int:
    for player in state.players:
        if player.player_id == player_id:
            return player.seat
    return 0


class TacticPolicy(L1RulePolicy):
    """L1 plus one candidate tactic, applied through a validated decision."""

    def __init__(
        self,
        *,
        seed: int,
        card: StrategyCard,
        settings: DeepSeekSettings | None = None,
    ) -> None:
        super().__init__(seed=seed)
        self.card = card
        self.settings = settings or DeepSeekSettings.from_environment()

    def _applies(self, state: GameState, actor: Player) -> bool:
        return actor.role.value == self.card.role and (
            self.card.phase == "ANY"
            or state.phase.value == self.card.phase
        )

    def choose_target(
        self,
        state: GameState,
        actor: Player,
        view,
        *,
        choice: str | None = None,
    ) -> str | None:
        if self._applies(state, actor) and self.settings.api_key and view.target_ids:
            picked = self._llm_target(state, actor, view)
            if picked in view.target_ids:
                return picked
        return super().choose_target(state, actor, view, choice=choice)

    def choose_choice(
        self,
        state: GameState,
        actor: Player,
        view,
    ) -> str | None:
        if self._applies(state, actor) and self.settings.api_key and view.choices:
            picked = self._llm_choice(state, actor, view)
            if picked in view.choices:
                return picked
        return super().choose_choice(state, actor, view)

    def _llm_target(self, state, actor, view) -> str | None:
        targets = [
            f"{player_id}（{_seat(state, player_id)} 号）"
            for player_id in view.target_ids
        ]
        system = (
            "你是狼人杀决策助手。根据战术卡和当前合法目标，选一个 target_id。"
            '只输出 JSON：{"target_id": "p?"}。只能从给定目标里选。'
        )
        user = (
            f"战术卡：{self.card.title}：{self.card.recommendation}\n"
            f"合法目标：{', '.join(targets)}\n"
            f"动作：{view.action}"
        )
        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.post(
                    f"{self.settings.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2,
                        "max_tokens": 80,
                    },
                )
                response.raise_for_status()
                payload = json.loads(
                    response.json()["choices"][0]["message"]["content"]
                )
                target = payload.get("target_id")
        except Exception:
            return None
        return target if isinstance(target, str) else None

    def _llm_choice(self, state, actor, view) -> str | None:
        system = (
            "你是狼人杀决策助手。根据战术卡和给定选项，选一个 choice。"
            '只输出 JSON：{"choice": "..."}。只能从给定选项里选。'
        )
        user = (
            f"战术卡：{self.card.title}：{self.card.recommendation}\n"
            f"可选：{', '.join(view.choices)}"
        )
        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.post(
                    f"{self.settings.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2,
                        "max_tokens": 40,
                    },
                )
                response.raise_for_status()
                payload = json.loads(
                    response.json()["choices"][0]["message"]["content"]
                )
                picked = payload.get("choice")
        except Exception:
            return None
        return picked if isinstance(picked, str) else None


def _run_wins(*, seed_start: int, games: int, policy_factory) -> dict[str, int]:
    wins = {"good": 0, "wolf": 0}
    for seed in range(seed_start, seed_start + games):
        summary, _actions = simulate_game(
            seed=seed,
            policy_name="l1",
            max_action_steps=600,
            max_days=20,
            policy=policy_factory(seed),
        )
        winner = summary.get("winner")
        if winner in wins:
            wins[winner] += 1
    return wins


def evaluate_candidate(
    candidate_id: str,
    *,
    strategy_root: Path | None = None,
    baseline_policy: str = "l1",
    seed_start: int = 1000,
    games: int = 200,
    settings: DeepSeekSettings | None = None,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    root = strategy_root or (PROJECT_ROOT / "strategy_library")
    library = StrategyLibrary(root)
    card = next(
        (
            candidate
            for candidate in library.load("candidate")
            if candidate.strategy_id == candidate_id
        ),
        None,
    )
    if card is None:
        raise ValueError(f"候选策略不存在：{candidate_id}")

    config = settings or DeepSeekSettings.from_environment()
    baseline_wins = _run_wins(
        seed_start=seed_start,
        games=games,
        policy_factory=lambda seed: L1RulePolicy(seed=seed),
    )
    candidate_wins = _run_wins(
        seed_start=seed_start,
        games=games,
        policy_factory=lambda seed: TacticPolicy(
            seed=seed, card=card, settings=config
        ),
    )

    base_good = baseline_wins["good"]
    cand_good = candidate_wins["good"]
    low, high = wilson_interval(cand_good, games)
    run_id = f"{candidate_id}:{seed_start}-{seed_start + games - 1}"
    result = {
        "candidate_id": candidate_id,
        "baseline_policy": baseline_policy,
        "seed_start": seed_start,
        "seed_end": seed_start + games - 1,
        "sample_size": games,
        "baseline_good_wins": base_good,
        "candidate_good_wins": cand_good,
        "baseline_good_win_rate": round(base_good / games, 4),
        "candidate_good_win_rate": round(cand_good / games, 4),
        "delta_good_win_rate": round((cand_good - base_good) / games, 4),
        "confidence_interval_95": [round(low, 4), round(high, 4)],
        "run_id": run_id,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        baseline_summary = out_dir / "baseline_summary.json"
        candidate_summary = out_dir / "candidate_summary.json"
        baseline_summary.write_text(
            json.dumps(baseline_wins, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        candidate_summary.write_text(
            json.dumps(candidate_wins, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        evidence = {
            "reviewer": "<填写审核人姓名>",
            "approved": False,
            "baseline_policy": baseline_policy,
            "candidate_policy": candidate_id,
            "seed_start": seed_start,
            "seed_end": seed_start + games - 1,
            "sample_size": games,
            "baseline_run_id": f"{run_id}-baseline",
            "candidate_run_id": f"{run_id}-candidate",
            "baseline_manifest_sha256": hashlib.sha256(
                baseline_summary.read_bytes()
            ).hexdigest(),
            "candidate_manifest_sha256": hashlib.sha256(
                candidate_summary.read_bytes()
            ).hexdigest(),
            "notes": (
                f"baseline_good_win_rate={result['baseline_good_win_rate']} "
                f"candidate_good_win_rate={result['candidate_good_win_rate']} "
                f"delta={result['delta_good_win_rate']} "
                f"ci95={result['confidence_interval_95']}"
            ),
        }
        (out_dir / "promotion_evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python -m backend.promote <candidate_id> [out_dir]")
        raise SystemExit(2)
    candidate = sys.argv[1]
    directory = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        Path("training_runs") / f"promote-{candidate}"
    )
    summary = evaluate_candidate(candidate, out_dir=directory)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
