"""Candidate evaluation, automatic gate and human approval of tactics.

Two ways a candidate may reach ``validated/``:

* ``auto_gate``: a paired 200-game comparison on the same seeds shows a
  statistically significant improvement (exact McNemar) and the effect size
  is at least ``AUTO_MIN_DELTA``. The gate records itself as reviewer
  ``auto-gate.v1`` so the provenance stays honest.
* ``human_review``: everything else stays in ``candidates/`` until a person
  runs ``python -m backend.promote approve <id> --reviewer <name>``.

Evaluation never calls a model: both arms are deterministic rule policies, so
the numbers are free to reproduce and the nightly budget is spent on review.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Sequence

import httpx

from .ai_growth import L1RulePolicy
from .ai_provider import DeepSeekSettings
from .game_engine import GameState, Player
from .simulator import simulate_game
from .strategy_library import (
    AUTO_GATE_REVIEWER,
    PromotionEvidence,
    StrategyCard,
    StrategyLibrary,
)
from .tactic_policy import DirectivePolicy, load_validated_directives
from .training import wilson_interval

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_ROOT = Path("training_runs") / "promotions"

AUTO_MIN_DELTA = 0.03
AUTO_MAX_P_VALUE = 0.05
REJECT_MIN_DELTA = -0.02
MIN_GAMES_FOR_GATE = 200


def _seat(state: GameState, player_id: str) -> int:
    for player in state.players:
        if player.player_id == player_id:
            return player.seat
    return 0


class TacticPolicy(L1RulePolicy):
    """L1 plus one candidate tactic, applied through an LLM target pick.

    Kept for interactive experiments. The nightly pipeline uses
    ``DirectivePolicy`` instead because it is free and deterministic.
    """

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


def mcnemar_exact_p(wins_only: int, losses_only: int) -> float:
    """Two-sided exact McNemar test on the discordant pairs."""

    if wins_only < 0 or losses_only < 0:
        raise ValueError("discordant counts must be non-negative")
    total = wins_only + losses_only
    if total == 0:
        return 1.0
    smaller = min(wins_only, losses_only)
    tail = sum(math.comb(total, index) for index in range(smaller + 1))
    return min(1.0, 2 * tail / (2**total))


def _paired_outcomes(
    *,
    seed_start: int,
    games: int,
    cards: Sequence[StrategyCard],
    candidate: StrategyCard | None,
) -> dict[str, Any]:
    """Run baseline and candidate on identical seeds, one game each."""

    baseline_wins = {"good": 0, "wolf": 0}
    candidate_wins = {"good": 0, "wolf": 0}
    wins_only = 0
    losses_only = 0
    for seed in range(seed_start, seed_start + games):
        base_summary, _ = simulate_game(
            seed=seed,
            policy_name="l1",
            max_action_steps=600,
            max_days=20,
            policy=DirectivePolicy(seed=seed, cards=cards),
        )
        base_winner = base_summary.get("winner")
        if base_winner in baseline_wins:
            baseline_wins[base_winner] += 1
        if candidate is None:
            continue
        cand_summary, _ = simulate_game(
            seed=seed,
            policy_name="l1",
            max_action_steps=600,
            max_days=20,
            policy=DirectivePolicy(seed=seed, cards=[*cards, candidate]),
        )
        cand_winner = cand_summary.get("winner")
        if cand_winner in candidate_wins:
            candidate_wins[cand_winner] += 1
        if cand_winner == "good" and base_winner != "good":
            wins_only += 1
        elif base_winner == "good" and cand_winner != "good":
            losses_only += 1
    return {
        "baseline": baseline_wins,
        "candidate": candidate_wins,
        "wins_only": wins_only,
        "losses_only": losses_only,
    }


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
    """Compare a candidate against the current validated policy on same seeds."""

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

    validated = load_validated_directives(root)
    outcomes = _paired_outcomes(
        seed_start=seed_start,
        games=games,
        cards=validated,
        candidate=card if card.directive else None,
    )
    base_good = outcomes["baseline"]["good"]
    cand_good = outcomes["candidate"]["good"]
    low, high = wilson_interval(cand_good, games)
    p_value = mcnemar_exact_p(
        outcomes["wins_only"], outcomes["losses_only"]
    )
    delta = (cand_good - base_good) / games
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
        "delta_good_win_rate": round(delta, 4),
        "confidence_interval_95": [round(low, 4), round(high, 4)],
        "discordant_candidate_wins": outcomes["wins_only"],
        "discordant_baseline_wins": outcomes["losses_only"],
        "mcnemar_exact_p": round(p_value, 6),
        "directive": card.directive,
        "run_id": run_id,
    }
    result["decision"] = classify_result(result)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        baseline_summary = out_dir / "baseline_summary.json"
        candidate_summary = out_dir / "candidate_summary.json"
        baseline_summary.write_text(
            json.dumps(outcomes["baseline"], ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        candidate_summary.write_text(
            json.dumps(outcomes["candidate"], ensure_ascii=False) + "\n",
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
            "decision_mode": "human_review",
            "notes": (
                f"baseline_good_win_rate={result['baseline_good_win_rate']} "
                f"candidate_good_win_rate={result['candidate_good_win_rate']} "
                f"delta={result['delta_good_win_rate']} "
                f"ci95={result['confidence_interval_95']} "
                f"mcnemar_p={result['mcnemar_exact_p']}"
            ),
        }
        (out_dir / "promotion_evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (out_dir / "evaluation.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def classify_result(result: dict[str, Any]) -> str:
    """Route a candidate to auto promotion, rejection or human review."""

    delta = float(result.get("delta_good_win_rate") or 0.0)
    p_value = float(result.get("mcnemar_exact_p") or 1.0)
    sample = int(result.get("sample_size") or 0)
    if result.get("directive") is None:
        return "human_review"
    if (
        sample >= MIN_GAMES_FOR_GATE
        and delta >= AUTO_MIN_DELTA
        and p_value <= AUTO_MAX_P_VALUE
    ):
        return "auto_promote"
    if sample >= MIN_GAMES_FOR_GATE and delta <= REJECT_MIN_DELTA and (
        p_value <= AUTO_MAX_P_VALUE or delta <= -0.05
    ):
        return "reject"
    return "human_review"


def evaluate_and_route(
    candidate_id: str,
    *,
    strategy_root: Path | None = None,
    seed_start: int = 7000,
    games: int = 200,
    out_root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate one candidate and apply the gate decision to the library."""

    root = strategy_root or (PROJECT_ROOT / "strategy_library")
    evidence_root = out_root or DEFAULT_EVIDENCE_ROOT
    out_dir = evidence_root / candidate_id.replace("/", "_")
    result = evaluate_candidate(
        candidate_id,
        strategy_root=root,
        seed_start=seed_start,
        games=games,
        out_dir=out_dir,
    )
    library = StrategyLibrary(root)
    decision = result["decision"]
    if decision == "auto_promote":
        evidence_path = out_dir / "promotion_evidence.json"
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        payload["reviewer"] = AUTO_GATE_REVIEWER
        payload["approved"] = True
        payload["decision_mode"] = "auto_gate"
        payload["notes"] = (
            f"auto gate: delta={result['delta_good_win_rate']} "
            f"p={result['mcnemar_exact_p']} n={result['sample_size']} "
            f"directive={result['directive']}"
        )
        evidence_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        evidence = PromotionEvidence.model_validate(payload)
        library.promote_candidate(candidate_id, evidence)
    elif decision == "reject":
        library.reject_candidate(
            candidate_id,
            (
                f"auto gate rejected: delta={result['delta_good_win_rate']} "
                f"p={result['mcnemar_exact_p']}"
            ),
        )
    return result


def approve_candidate(
    candidate_id: str,
    reviewer: str,
    *,
    strategy_root: Path | None = None,
    seed_start: int = 7000,
    games: int = 200,
    out_root: Path | None = None,
    skip_evaluation: bool = False,
) -> dict[str, Any]:
    """Human sign-off: flip the evidence and move the card to validated."""

    name = reviewer.strip()
    if not name or name.lower() in {"ai", "agent", "model", AUTO_GATE_REVIEWER}:
        raise ValueError("请填写真实审核人姓名")
    root = strategy_root or (PROJECT_ROOT / "strategy_library")
    evidence_root = out_root or DEFAULT_EVIDENCE_ROOT
    out_dir = evidence_root / candidate_id.replace("/", "_")
    evidence_path = out_dir / "promotion_evidence.json"
    evaluation_path = out_dir / "evaluation.json"
    if skip_evaluation:
        # Admin direct approval: keep the candidate enterable for a demo
        # without a multi-minute evaluation, and record that it was skipped.
        payload: dict[str, Any] = {
            "reviewer": name,
            "approved": True,
            "baseline_policy": "l1",
            "candidate_policy": candidate_id,
            "seed_start": 0,
            "seed_end": 0,
            "sample_size": 0,
            "baseline_run_id": "skipped",
            "candidate_run_id": "skipped",
            "baseline_manifest_sha256": "0" * 64,
            "candidate_manifest_sha256": "0" * 64,
            "decision_mode": "human_review",
            "notes": f"human direct approval by {name}; evaluation skipped",
        }
    else:
        if not evidence_path.is_file():
            evaluate_candidate(
                candidate_id,
                strategy_root=root,
                seed_start=seed_start,
                games=games,
                out_dir=out_dir,
            )
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        payload["reviewer"] = name
        payload["approved"] = True
        payload["decision_mode"] = "human_review"
        evaluation = (
            json.loads(evaluation_path.read_text(encoding="utf-8"))
            if evaluation_path.is_file()
            else {}
        )
        payload["notes"] = (
            f"human approval by {name}; "
            f"delta={evaluation.get('delta_good_win_rate', 'n/a')} "
            f"p={evaluation.get('mcnemar_exact_p', 'n/a')}"
        )[:1000]
        evidence_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    card = StrategyLibrary(root).promote_candidate(
        candidate_id,
        PromotionEvidence.model_validate(payload),
    )
    return {
        "strategy_id": card.strategy_id,
        "status": card.status,
        "reviewer": name,
        "approved_at": datetime.now(UTC).isoformat(),
    }


def pending_candidates(strategy_root: Path | None = None) -> list[dict[str, Any]]:
    root = strategy_root or (PROJECT_ROOT / "strategy_library")
    rows: list[dict[str, Any]] = []
    for card in StrategyLibrary(root).load("candidate"):
        rows.append(
            {
                "strategy_id": card.strategy_id,
                "title": card.title,
                "role": card.role,
                "phase": card.phase,
                "action": card.action,
                "directive": card.directive,
                "created_at": card.created_at,
            }
        )
    rows.sort(key=lambda row: row["created_at"], reverse=True)
    return rows


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WolfArena 战术候选晋级")
    parser.add_argument("--root", type=Path, default=Path("strategy_library"))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("pending", help="列出待人工确认的候选")

    evaluate = sub.add_parser("evaluate", help="跑 200 局对照并写入证据")
    evaluate.add_argument("candidate_id")
    evaluate.add_argument("--games", type=int, default=200)
    evaluate.add_argument("--seed-start", type=int, default=7000)

    approve = sub.add_parser("approve", help="人工点头并入库")
    approve.add_argument("candidate_id")
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--games", type=int, default=200)
    approve.add_argument("--seed-start", type=int, default=7000)

    rollback = sub.add_parser("rollback", help="把已验证策略退回候选")
    rollback.add_argument("strategy_id")
    rollback.add_argument("--reason", default="manual rollback")

    args = parser.parse_args(argv)
    if args.command == "pending":
        print(json.dumps(pending_candidates(args.root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "evaluate":
        result = evaluate_and_route(
            args.candidate_id,
            strategy_root=args.root,
            seed_start=args.seed_start,
            games=args.games,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "approve":
        result = approve_candidate(
            args.candidate_id,
            args.reviewer,
            strategy_root=args.root,
            seed_start=args.seed_start,
            games=args.games,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    path = StrategyLibrary(args.root).rollback(args.strategy_id, args.reason)
    print(json.dumps({"rolled_back": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
