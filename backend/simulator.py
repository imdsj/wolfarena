"""CLI simulator for reproducible AI-only nine-player games."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Sequence

from .actions import available_actions_for_state, execute_engine_action
from .ai_controller import AIController, AIControllerStep
from .ai_growth import L0Policy
from .game_engine import (
    EventType,
    GameState,
    Phase,
    check_winner,
    create_game,
    get_player,
)


SUPPORTED_POLICIES = ("l0",)
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
        "is_system": plan.is_system,
        "legal_actions": [view.action for view in views],
        "action": plan.request.action,
        "target_id": plan.request.target_id,
        "choice": plan.request.choice,
        "content": plan.request.content,
        "succeeded": False,
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

    summary = {
        "game_id": game_id,
        "seed": seed,
        "policy": policy.strategy_id,
        "status": status,
        "terminal_phase": state.phase.value,
        "winner": _winner_value(state) if state.phase is Phase.END else None,
        "action_steps": step,
        "day": state.day,
        "roles": _roles_by_player(state),
        "alive_player_ids": [
            player.player_id for player in state.players if player.is_alive
        ],
        "error": error,
        "duration_ms": round((perf_counter() - started_at) * 1000, 3),
    }
    return summary, actions


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
        },
        "summary": {
            "games_completed": completed,
            "games_failed": failed,
            "action_steps": len(actions),
        },
        "failed_game_ids": [
            game["game_id"] for game in games if game["status"] != "completed"
        ],
    }

    (out / "run.json").write_text(
        json.dumps(run_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(out / "games.jsonl", games)
    _write_jsonl(out / "actions.jsonl", actions)
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = SimulationConfig(
        games=args.games,
        seed_start=args.seed_start,
        policy=args.policy,
        output_directory=args.out,
        max_action_steps=args.max_steps,
        max_days=args.max_days,
        allow_self_destruct=not args.no_self_destruct,
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
