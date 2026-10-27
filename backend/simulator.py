"""CLI simulator for reproducible AI-only nine-player games."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
import shlex
import subprocess
import sys
from time import perf_counter
from typing import Any, Sequence

from .actions import available_actions_for_state, execute_engine_action
from .ai_controller import AIController, AIControllerStep
from .ai_growth import L0Policy, L1RulePolicy
from .game_engine import (
    EventType,
    GameState,
    Phase,
    check_winner,
    create_game,
    get_player,
)


SUPPORTED_POLICIES = ("l0", "l1")
DEFAULT_HOST_PLAYER_ID = "p1"


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Validated controls for one simulation batch."""

    games: int
    seed_start: int
    policy: str
    output_directory: Path
    max_action_steps: int = 600
    max_days: int = 20
    allow_self_destruct: bool = True
    command: str | None = None
    code_commit: str | None = None

    def __post_init__(self) -> None:
        if self.games <= 0:
            raise ValueError("games 必须大于 0")
        if self.seed_start < 0:
            raise ValueError("seed_start 不能小于 0")
        if self.policy not in SUPPORTED_POLICIES:
            raise ValueError(
                f"不支持的策略版本：{self.policy}；当前仅支持 "
                f"{', '.join(SUPPORTED_POLICIES)}"
            )
        if self.max_action_steps <= 0:
            raise ValueError("max_action_steps 必须大于 0")
        if self.max_days <= 0:
            raise ValueError("max_days 必须大于 0")


def _policy_for(name: str, *, seed: int):
    if name == "l0":
        return L0Policy(seed=seed)
    if name == "l1":
        return L1RulePolicy(seed=seed)
    raise ValueError(f"不支持的策略版本：{name}")


def _state_signature(state: GameState) -> tuple[Any, ...]:
    day_result = state.day_result
    night_result = state.night_result
    return (
        state.phase,
        state.day,
        len(state.events),
        state.wolf_captain_id,
        tuple(
            (player.player_id, player.is_alive)
            for player in state.players
        ),
        None
        if night_result is None
        else (
            night_result.wolf_target_id,
            night_result.seer_target_id,
            night_result.witch_action_submitted,
            night_result.resolved,
        ),
        None
        if day_result is None
        else (
            day_result.next_speaker_index,
            tuple(day_result.last_words_queue),
            tuple(sorted(day_result.votes.items())),
            day_result.votes_closed,
            day_result.vote_resolved,
            day_result.banishment_pending,
        ),
    )


def _winner_value(state: GameState) -> str | None:
    for event in reversed(state.events):
        if event.event_type is EventType.WINNER_DECIDED:
            value = event.data.get("winner")
            return value if isinstance(value, str) else None
    winner = check_winner(state)
    return winner.value if winner is not None else None


def _roles_by_player(state: GameState) -> dict[str, str]:
    return {
        player.player_id: player.role.value
        for player in sorted(state.players, key=lambda item: item.seat)
    }


def _replay_sha256(
    *,
    roles: dict[str, str],
    winner: str | None,
    terminal_phase: str,
    action_steps: int,
    day: int,
    actions: Sequence[dict[str, Any]],
) -> str:
    canonical = json.dumps(
        {
            "roles": roles,
            "winner": winner,
            "terminal_phase": terminal_phase,
            "actions": [
                {
                    key: action.get(key)
                    for key in (
                        "step",
                        "day",
                        "phase",
                        "actor_id",
                        "actor_role",
                        "is_system",
                        "legal_actions",
                        "action",
                        "target_id",
                        "choice",
                        "content",
                        "ok",
                        "phase_after",
                        "event_seq_after",
                    )
                }
                for action in actions
            ],
            "action_steps": action_steps,
            "day": day,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _base_action_record(
    *,
    game_id: str,
    seed: int,
    policy,
    step: int,
    state: GameState,
    plan: AIControllerStep,
    now: float,
) -> dict[str, Any]:
    actor = plan.actor or get_player(state, DEFAULT_HOST_PLAYER_ID)
    views = available_actions_for_state(
        state,
        actor,
        host_player_id=DEFAULT_HOST_PLAYER_ID,
        now=now,
    )
    return {
        "game_id": game_id,
        "seed": seed,
        "policy": policy.strategy_id,
        "step": step,
        "day": state.day,
        "phase": state.phase.value,
        "event_seq_before": state.events[-1].event_seq if state.events else -1,
        "actor_id": None if plan.is_system else actor.player_id,
        "actor_role": actor.role.value,
        "actor": "system" if plan.is_system else actor.player_id,
        "role": "system" if plan.is_system else actor.role.value,
        "is_system": plan.is_system,
        "legal_actions": [view.action for view in views],
        "action": plan.request.action,
        "target_id": plan.request.target_id,
        "target": plan.request.target_id,
        "choice": plan.request.choice,
        "content": plan.request.content,
        "succeeded": False,
        "ok": False,
        "error": None,
        "simulated_time": now,
    }


def simulate_game(
    *,
    seed: int,
    policy_name: str,
    max_action_steps: int,
    max_days: int,
    allow_self_destruct: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run one game through the shared action layer and return auditable logs."""

    game_id = f"seed-{seed}"
    policy = _policy_for(policy_name, seed=seed)
    state = create_game(seed=seed, human_count=0)
    controller = AIController(None)
    actions: list[dict[str, Any]] = []
    started_at = perf_counter()
    current_time = 1_000.0
    step = 0
    status = "completed"
    error: dict[str, str] | None = None

    while state.phase is not Phase.END:
        if step >= max_action_steps:
            status = "error"
            error = {
                "type": "max_action_steps",
                "message": f"达到最大动作步数 {max_action_steps}",
            }
            break
        if state.day > max_days:
            status = "error"
            error = {
                "type": "max_days",
                "message": f"达到最大天数 {max_days}",
            }
            break

        plan = controller.plan_next_step(
            state,
            policy=policy,
            now=current_time,
            skip_optional_self_destruct=not allow_self_destruct,
            auto_close_vote=True,
            auto_start_game=True,
        )
        if plan is None:
            if (
                state.phase is Phase.SELF_DESTRUCT
                and state.day_result is not None
                and state.day_result.self_destruct_deadline is not None
            ):
                current_time = max(
                    current_time,
                    state.day_result.self_destruct_deadline,
                )
                continue
            status = "error"
            error = {
                "type": "no_legal_action",
                "message": (
                    f"阶段 {state.phase.value} 没有可推进动作"
                ),
            }
            break

        step += 1
        record = _base_action_record(
            game_id=game_id,
            seed=seed,
            policy=policy,
            step=step,
            state=state,
            plan=plan,
            now=current_time,
        )
        actor = plan.actor or get_player(state, DEFAULT_HOST_PLAYER_ID)
        state_before = deepcopy(state)
        signature_before = _state_signature(state)
        try:
            execute_engine_action(
                state,
                actor,
                plan.request,
                host_player_id=DEFAULT_HOST_PLAYER_ID,
                now=current_time,
            )
        except Exception as exc:
            state = state_before
            record["error"] = f"{exc.__class__.__name__}: {exc}"
            actions.append(record)
            status = "error"
            error = {
                "type": "action_exception",
                "message": record["error"],
            }
            break

        record["succeeded"] = True
        record["ok"] = True
        record["event_seq_after"] = (
            state.events[-1].event_seq if state.events else -1
        )
        record["phase_after"] = state.phase.value
        actions.append(record)
        if _state_signature(state) == signature_before:
            status = "error"
            error = {
                "type": "state_not_advanced",
                "message": (
                    f"动作 {plan.request.action} 未改变阶段或回合状态"
                ),
            }
            break

        if (
            state.phase is Phase.SELF_DESTRUCT
            and state.day_result is not None
            and state.day_result.self_destruct_deadline is not None
        ):
            current_time = state.day_result.self_destruct_deadline
        else:
            current_time += 1.0

    winner = _winner_value(state) if state.phase is Phase.END else None
    roles = _roles_by_player(state)
    summary = {
        "game_id": game_id,
        "seed": seed,
        "policy": policy.strategy_id,
        "status": status,
        "terminal_phase": state.phase.value,
        "winner": winner,
        "action_steps": step,
        "steps": step,
        "day": state.day,
        "days": state.day,
        "roles": roles,
        "replay_sha256": _replay_sha256(
            roles=roles,
            winner=winner,
            terminal_phase=state.phase.value,
            action_steps=step,
            day=state.day,
            actions=actions,
        ),
        "alive_player_ids": [
            player.player_id for player in state.players if player.is_alive
        ],
        "error": error,
        "duration_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    return summary, actions


def compute_metrics(
    games: Sequence[dict[str, Any]],
    actions: Sequence[dict[str, Any]],
    *,
    policy: str,
    seed_start: int,
    seed_end: int,
) -> dict[str, Any]:
    """Compute reproducible metrics from exported game and action rows."""

    total_games = len(games)
    completed_games = [
        game
        for game in games
        if game["status"] == "completed"
        and game["terminal_phase"] == "END"
    ]
    valid_games = [
        game
        for game in completed_games
        if game["winner"] in {"good", "wolf"}
    ]
    successful_actions = sum(bool(action["ok"]) for action in actions)
    submitted_actions = len(actions)
    action_counts = Counter(
        action["action"] for action in actions if action["ok"]
    )
    winner_counts = Counter(game["winner"] for game in valid_games)
    errors = Counter(
        game["error"]["type"]
        for game in games
        if game["status"] != "completed" and game["error"] is not None
    )
    valid_count = len(valid_games)
    completed_durations = [
        game["duration_ms"] for game in completed_games
    ]
    completed_steps = [game["steps"] for game in completed_games]

    return {
        "policy": policy,
        "seed_start": seed_start,
        "seed_end": seed_end,
        "total_games": total_games,
        "completed_games": len(completed_games),
        "valid_completed_games": valid_count,
        "failed_games": total_games - len(completed_games),
        "completion_rate": (
            len(completed_games) / total_games if total_games else None
        ),
        "actions_submitted": submitted_actions,
        "actions_succeeded": successful_actions,
        "actions_failed": submitted_actions - successful_actions,
        "action_legal_rate": (
            successful_actions / submitted_actions
            if submitted_actions
            else None
        ),
        "action_counts": dict(sorted(action_counts.items())),
        "action_frequency_per_game": {
            action: count / total_games
            for action, count in sorted(action_counts.items())
        }
        if total_games
        else {},
        "faction_win_counts": {
            "good": winner_counts["good"],
            "wolf": winner_counts["wolf"],
        },
        "faction_win_rates": {
            "good": (
                winner_counts["good"] / valid_count if valid_count else None
            ),
            "wolf": (
                winner_counts["wolf"] / valid_count if valid_count else None
            ),
        },
        "average_steps": (
            sum(completed_steps) / len(completed_steps)
            if completed_steps
            else None
        ),
        "average_duration_ms": (
            sum(completed_durations) / len(completed_durations)
            if completed_durations
            else None
        ),
        "total_duration_ms": sum(completed_durations),
        "errors_by_type": dict(sorted(errors.items())),
    }


def _roles_rows(games: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for game in games:
        for player_id, role in game["roles"].items():
            rows.append(
                {
                    "game_id": game["game_id"],
                    "seed": game["seed"],
                    "player_id": player_id,
                    "seat": int(player_id[1:]),
                    "role": role,
                }
            )
    return rows


def _resolve_code_commit(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            check=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    value = result.stdout.strip()
    return value or "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_simulation(config: SimulationConfig) -> dict[str, Any]:
    """Run a configured batch and write JSON/JSONL outputs."""

    out = config.output_directory
    out.mkdir(parents=True, exist_ok=True)
    run_started = perf_counter()
    run_started_at = datetime.now(UTC).isoformat()
    games: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    for offset in range(config.games):
        seed = config.seed_start + offset
        summary, game_actions = simulate_game(
            seed=seed,
            policy_name=config.policy,
            max_action_steps=config.max_action_steps,
            max_days=config.max_days,
            allow_self_destruct=config.allow_self_destruct,
        )
        games.append(summary)
        actions.extend(game_actions)

    completed = sum(game["status"] == "completed" for game in games)
    failed = len(games) - completed
    metrics = compute_metrics(
        games,
        actions,
        policy=config.policy,
        seed_start=config.seed_start,
        seed_end=config.seed_start + config.games - 1,
    )
    code_commit = _resolve_code_commit(config.code_commit)
    command = config.command or " ".join(
        [
            "python",
            "-m",
            "backend.simulator",
            "--games",
            str(config.games),
            "--seed-start",
            str(config.seed_start),
            "--policy",
            config.policy,
            "--out",
            str(out),
        ]
    )
    run_summary = {
        "run_id": (
            f"{config.policy}-{config.seed_start}-"
            f"{config.seed_start + config.games - 1}"
        ),
        "started_at": run_started_at,
        "finished_at": datetime.now(UTC).isoformat(),
        "duration_ms": round((perf_counter() - run_started) * 1000, 3),
        "config": {
            "games": config.games,
            "seed_start": config.seed_start,
            "policy": config.policy,
            "max_action_steps": config.max_action_steps,
            "max_days": config.max_days,
            "allow_self_destruct": config.allow_self_destruct,
            "output_directory": str(out.resolve()),
            "code_commit": code_commit,
            "command": command,
        },
        "summary": {
            "games_completed": completed,
            "games_failed": failed,
            "action_steps": len(actions),
        },
        "failed_game_ids": [
            game["game_id"] for game in games if game["status"] != "completed"
        ],
        "metrics": metrics,
    }

    (out / "run.json").write_text(
        json.dumps(run_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(out / "games.jsonl", games)
    _write_jsonl(out / "actions.jsonl", actions)
    roles = _roles_rows(games)
    (out / "roles.json").write_text(
        json.dumps(roles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "run_id": run_summary["run_id"],
        "generated_at": run_summary["finished_at"],
        "code_commit": code_commit,
        "command": command,
        "policy": config.policy,
        "policy_version": games[0]["policy"] if games else None,
        "python_version": platform.python_version(),
        **metrics,
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    hashed_files = (
        "run.json",
        "games.jsonl",
        "actions.jsonl",
        "roles.json",
        "summary.json",
    )
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "code_commit": code_commit,
        "command": command,
        "python_version": platform.python_version(),
        "policy": config.policy,
        "policy_version": games[0]["policy"] if games else None,
        "seed_start": config.seed_start,
        "seed_end": config.seed_start + config.games - 1,
        "hash_algorithm": "sha256",
        "files": {
            name: {
                "sha256": _sha256(out / name),
                "bytes": (out / name).stat().st_size,
            }
            for name in hashed_files
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return run_summary


def _write_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是大于 0 的整数")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("不能小于 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="WolfArena AI-only deterministic simulator",
    )
    parser.add_argument("--games", type=_positive_int, default=10)
    parser.add_argument(
        "--seed-start",
        type=_non_negative_int,
        default=1000,
    )
    parser.add_argument("--policy", choices=SUPPORTED_POLICIES, default="l0")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-steps", type=_positive_int, default=600)
    parser.add_argument("--max-days", type=_positive_int, default=20)
    parser.add_argument(
        "--no-self-destruct",
        action="store_true",
        help="禁止策略主动选择可选自爆动作",
    )
    parser.add_argument(
        "--commit",
        default=None,
        help="写入 manifest 的代码提交；默认尝试读取 git HEAD",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    command = "python -m backend.simulator " + shlex.join(raw_argv)
    config = SimulationConfig(
        games=args.games,
        seed_start=args.seed_start,
        policy=args.policy,
        output_directory=args.out,
        max_action_steps=args.max_steps,
        max_days=args.max_days,
        allow_self_destruct=not args.no_self_destruct,
        command=command,
        code_commit=args.commit,
    )
    try:
        summary = run_simulation(config)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["summary"]["games_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
