"""Overnight self-play -> review -> evaluate -> promote loop.

One round is:

1. AI-vs-AI games with the *currently validated* tactics (free, deterministic).
2. A few of those games are reviewed by the model into candidate cards
   (the only paid step, capped by ``--budget``).
3. Each new candidate is compared against today's validated policy on the same
   200 held-out seeds (free, deterministic).
4. The gate promotes clear winners, rejects clear losers and leaves anything
   ambiguous for a human.

The loop is resumable: ``state.json`` stores the next training seed and the
accumulated spend, so stopping with Ctrl+C and restarting continues forward
instead of repeating seeds.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable, Sequence

from .ai_provider import DeepSeekSettings
from .llm_budget import LEDGER
from .promote import evaluate_and_route
from .review import card_from_review
from .simulator import simulate_game
from .strategy_library import StrategyCard, StrategyError, StrategyLibrary
from .tactic_policy import DirectivePolicy, load_validated_directives

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = Path("training_runs") / "autotrain"
EVAL_WINDOWS = (7000, 8000, 9000, 10000)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _directive_key(card: StrategyCard) -> tuple[str, str, str] | None:
    if not card.directive:
        return None
    return (card.role, card.action, card.directive)


def known_keys(library: StrategyLibrary) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for status in ("validated", "candidate"):
        for card in library.load(status):
            key = _directive_key(card)
            if key:
                keys.add(key)
    return keys


def eval_window_for(candidate_id: str) -> int:
    digest = hashlib.sha1(candidate_id.encode()).hexdigest()
    return EVAL_WINDOWS[int(digest[:8], 16) % len(EVAL_WINDOWS)]


def simulate_batch(
    *,
    round_dir: Path,
    seeds: Sequence[int],
    cards: Sequence[StrategyCard],
) -> list[dict[str, Any]]:
    """Run the nine-player AI-only games and write review-compatible logs."""

    # Self-play must stay free: LLM speech is for human games only.
    previous = os.environ.get("WOLFARENA_LLM_SPEECH")
    os.environ["WOLFARENA_LLM_SPEECH"] = "0"
    round_dir.mkdir(parents=True, exist_ok=True)
    games: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    try:
        for seed in seeds:
            summary, game_actions = simulate_game(
                seed=seed,
                policy_name="l1",
                max_action_steps=600,
                max_days=20,
                policy=DirectivePolicy(seed=seed, cards=cards),
            )
            games.append(summary)
            actions.extend(game_actions)
    finally:
        if previous is None:
            os.environ.pop("WOLFARENA_LLM_SPEECH", None)
        else:
            os.environ["WOLFARENA_LLM_SPEECH"] = previous
    _write_jsonl(round_dir / "games.jsonl", games)
    _write_jsonl(round_dir / "actions.jsonl", actions)
    return games


def review_games(
    *,
    games: Sequence[dict[str, Any]],
    actions: Sequence[dict[str, Any]],
    library: StrategyLibrary,
    settings: DeepSeekSettings,
    limit: int,
    known: set[tuple[str, str, str]],
) -> tuple[list[StrategyCard], int]:
    """Review up to ``limit`` finished games into new, distinct candidates."""

    created: list[StrategyCard] = []
    skipped = 0
    reviewed = 0
    by_seed: dict[int, list[dict[str, Any]]] = {}
    for action in actions:
        by_seed.setdefault(action.get("seed", 0), []).append(action)
    for game in games:
        if reviewed >= limit:
            break
        if game.get("status") != "completed" or not game.get("winner"):
            continue
        reviewed += 1
        card = card_from_review(
            game=game,
            actions=by_seed.get(game.get("seed", 0), []),
            settings=settings,
        )
        key = _directive_key(card)
        if key is None or key in known:
            skipped += 1
            continue
        try:
            library.record_candidate(card)
        except StrategyError:
            skipped += 1
            continue
        known.add(key)
        created.append(card)
    return created, skipped


def load_state(path: Path, *, seed_start: int) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "next_seed": seed_start,
        "rounds_done": 0,
        "spend_cny": 0.0,
        "created_at": datetime.now(UTC).isoformat(),
    }


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(UTC).isoformat()
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_autotrain(
    *,
    out_root: Path = DEFAULT_OUT,
    strategy_root: Path | None = None,
    hours: float = 5.0,
    budget_cny: float = 15.0,
    rounds: int = 1000,
    games_per_round: int = 20,
    review_limit: int = 3,
    eval_games: int = 200,
    seed_start: int = 10000,
    settings: DeepSeekSettings | None = None,
) -> dict[str, Any]:
    root = strategy_root or (PROJECT_ROOT / "strategy_library")
    library = StrategyLibrary(root)
    config = settings or DeepSeekSettings.from_environment()
    out_root.mkdir(parents=True, exist_ok=True)
    state_path = out_root / "state.json"
    report_path = out_root / "report.md"
    rounds_path = out_root / "rounds.jsonl"
    state = load_state(state_path, seed_start=seed_start)

    LEDGER.reset(limit_cny=budget_cny)
    started = time.monotonic()
    deadline = started + hours * 3600
    round_log: list[dict[str, Any]] = []

    if not report_path.exists():
        report_path.write_text(
            "# WolfArena 夜间自训练报告\n\n"
            "自动晋级 = 同 seed 200 局配对比较、McNemar p<=0.05 且 "
            "delta>=3%；其余进入人工确认队列。\n\n",
            encoding="utf-8",
        )

    for _ in range(rounds):
        if time.monotonic() >= deadline:
            break
        if not LEDGER.can_spend(0.02):
            break
        round_index = int(state["rounds_done"]) + 1
        seeds = list(
            range(int(state["next_seed"]), int(state["next_seed"]) + games_per_round)
        )
        round_dir = out_root / f"round-{round_index:04d}"
        entry: dict[str, Any] = {
            "round": round_index,
            "seeds": [seeds[0], seeds[-1]],
            "created": [],
            "skipped": 0,
            "evaluated": [],
            "errors": [],
        }
        try:
            cards = load_validated_directives(root)
            games = simulate_batch(round_dir=round_dir, seeds=seeds, cards=cards)
            produced, skipped = review_games(
                games=games,
                actions=_read_jsonl(round_dir / "actions.jsonl"),
                library=library,
                settings=config,
                limit=review_limit,
                known=known_keys(library),
            )
            entry["skipped"] = skipped
            entry["created"] = [card.strategy_id for card in produced]
            if not config.api_key:
                entry["errors"].append(
                    "no_api_key: using deterministic fallback lessons"
                )
            for card in produced:
                result = evaluate_and_route(
                    card.strategy_id,
                    strategy_root=root,
                    seed_start=eval_window_for(card.strategy_id),
                    games=eval_games,
                )
                entry["evaluated"].append(
                    {
                        "strategy_id": result["candidate_id"],
                        "directive": result["directive"],
                        "delta": result["delta_good_win_rate"],
                        "p": result["mcnemar_exact_p"],
                        "decision": result["decision"],
                    }
                )
        except Exception as error:  # a bad round must not kill the night
            entry["errors"].append(f"{type(error).__name__}: {error}")
        state["next_seed"] = seeds[-1] + 1
        state["rounds_done"] = round_index
        state["spend_cny"] = round(LEDGER.cost_cny, 4)
        save_state(state_path, state)
        entry["spend_cny"] = round(LEDGER.cost_cny, 4)
        round_log.append(entry)
        with rounds_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _append_report(report_path, entry, library)
        print(
            f"round {round_index}: seeds={seeds[0]}-{seeds[-1]} "
            f"created={len(entry['created'])} "
            f"spend={entry['spend_cny']}CNY"
        )

    summary = {
        "rounds": len(round_log),
        "spend": LEDGER.summary(),
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "library": library.counts(),
        "next_seed": state["next_seed"],
        "report": str(report_path),
    }
    (out_root / "last_run.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _append_report(path: Path, entry: dict[str, Any], library: StrategyLibrary) -> None:
    lines = [
        f"## 第 {entry['round']} 轮  seeds={entry['seeds'][0]}-{entry['seeds'][1]}",
        "",
        f"- 新增候选：{len(entry['created'])}",
        f"- 跳过重复：{entry['skipped']}",
        f"- 累计花费：{entry['spend_cny']} 元（估算）",
    ]
    for row in entry["evaluated"]:
        lines.append(
            f"- `{row['strategy_id']}` {row['directive']} "
            f"delta={row['delta']:+.3f} p={row['p']} -> **{row['decision']}**"
        )
    for error in entry["errors"]:
        lines.append(f"- 错误：{error}")
    counts = library.counts()
    lines.append(
        f"- 库状态：seed={counts['seed']} candidate={counts['candidate']} "
        f"validated={counts['validated']} rejected={counts['rejected']}"
    )
    lines.append("")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WolfArena 夜间自训练")
    parser.add_argument("--hours", type=float, default=5.0)
    parser.add_argument("--budget", type=float, default=15.0)
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument("--review-games", type=int, default=3)
    parser.add_argument("--eval-games", type=int, default=200)
    parser.add_argument("--seed-start", type=int, default=10000)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    summary = run_autotrain(
        out_root=args.out,
        hours=args.hours,
        budget_cny=args.budget,
        rounds=args.rounds,
        games_per_round=args.games,
        review_limit=args.review_games,
        eval_games=args.eval_games,
        seed_start=args.seed_start,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
