"""Offline RAG ablation: no retrieval vs keyword vs structured retrieval.

The scenarios are fixed and deterministic. Each one names the tactics a human
reviewer would expect for that board, so Recall@3 is measurable without any
external model or embedding service.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .game_engine import (
    EventType,
    GameState,
    Phase,
    Role,
    Visibility,
    append_event,
    create_game,
)
from .strategy_library import StrategyCard, StrategyLibrary
from .tactic_retrieval import build_context, rank_tactics


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIBRARY_ROOT = PROJECT_ROOT / "strategy_library"


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    role: Role
    phase: Phase
    speeches: tuple[tuple[int, str], ...] = ()
    votes: tuple[dict[int, int | None], ...] = ()
    expected: tuple[str, ...] = ()


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        name="村民遇到一晚两验",
        role=Role.VILLAGER,
        phase=Phase.DAY_DISCUSSION,
        speeches=((5, "我是预言家，昨晚验4号金水、2号查杀。"),),
        expected=("good.hard-rule-first",),
    ),
    Scenario(
        name="村民遇到未发言断言神职",
        role=Role.VILLAGER,
        phase=Phase.DAY_DISCUSSION,
        speeches=((8, "3号才是真预言家，今天听他的。"),),
        expected=("good.catch-impossible-identity",),
    ),
    Scenario(
        name="村民看两天同票",
        role=Role.VILLAGER,
        phase=Phase.DAY_DISCUSSION,
        votes=(
            {1: 3, 2: 3, 3: 1, 4: None},
            {1: 5, 2: 5, 3: 1, 4: 5},
        ),
        expected=("good.read-vote-blocs",),
    ),
    Scenario(
        name="村民投票阶段多人指认",
        role=Role.VILLAGER,
        phase=Phase.VOTE,
        speeches=(
            (1, "5号是狼，今天票5号。"),
            (2, "我也觉得5号有问题，票5号。"),
        ),
        expected=("cand.vote-most-accused.v1",),
    ),
    Scenario(
        name="预言家夜间查验",
        role=Role.SEER,
        phase=Phase.NIGHT_SEER_CHECK,
        expected=("seer.check-unverified",),
    ),
    Scenario(
        name="预言家遇到对跳",
        role=Role.SEER,
        phase=Phase.NIGHT_SEER_CHECK,
        speeches=(
            (4, "我是预言家，我验了6号是狼。"),
            (5, "我才是真预言家，4号是假跳。"),
        ),
        expected=("seer.check-counterclaim",),
    ),
    Scenario(
        name="狼人夜间刀神职",
        role=Role.WEREWOLF,
        phase=Phase.NIGHT_WOLF_KILL,
        speeches=((4, "我是预言家，6号是狼。"),),
        expected=("wolf.kill-claimed-seer",),
    ),
    Scenario(
        name="女巫夜间见查杀",
        role=Role.WITCH,
        phase=Phase.NIGHT_WITCH_ACTION,
        speeches=((4, "我是预言家，我验了6号是狼。"),),
        expected=("witch.poison-high-confidence",),
    ),
    Scenario(
        name="猎人白天开枪",
        role=Role.HUNTER,
        phase=Phase.DAY_HUNTER_SHOT,
        speeches=(
            (1, "5号是狼，今天票5号。"),
            (2, "5号发言很虚，票5号。"),
        ),
        expected=("hunter.shot-consensus-wolf",),
    ),
    Scenario(
        name="狼人白天深水",
        role=Role.WEREWOLF,
        phase=Phase.DAY_DISCUSSION,
        expected=("wolf.no-unspoken-identity",),
    ),
    Scenario(
        name="女巫白天回应对跳",
        role=Role.WITCH,
        phase=Phase.DAY_DISCUSSION,
        speeches=((4, "我是预言家，6号查杀。"),),
        expected=("witch.respond-counterclaim",),
    ),
    Scenario(
        name="投票阶段金水反投",
        role=Role.VILLAGER,
        phase=Phase.VOTE,
        speeches=((4, "我是预言家，3号是金水，今天票3号。"),),
        expected=("good.seer-report-needs-claim",),
    ),
)


def _player_by_seat(state: GameState, seat: int):
    return next(player for player in state.players if player.seat == seat)


def build_scenario_state(
    scenario: Scenario,
    *,
    seed: int = 9000,
) -> tuple[GameState, object]:
    state = create_game(seed=seed, human_count=0)
    state.phase = scenario.phase
    state.day = 1
    actor = next(
        player for player in state.players if player.role is scenario.role
    )
    for seat, content in scenario.speeches:
        speaker = _player_by_seat(state, seat)
        append_event(
            state,
            EventType.PUBLIC_SPEECH,
            actor_id=speaker.player_id,
            visibility=Visibility.PUBLIC,
            data={"content": content},
        )
    for day, row in enumerate(scenario.votes, start=1):
        state.day = day
        votes = {
            _player_by_seat(state, voter).player_id: (
                _player_by_seat(state, target).player_id
                if target is not None
                else None
            )
            for voter, target in row.items()
        }
        append_event(
            state,
            EventType.VOTE_RESULT,
            visibility=Visibility.PUBLIC,
            data={"votes": votes},
        )
    state.day = max(1, len(scenario.votes) or 1)
    state.phase = scenario.phase
    return state, actor


def _no_retrieval(
    library: StrategyLibrary,
    role: str,
    phase: str,
    limit: int = 3,
) -> list[str]:
    cards: list[StrategyCard] = [
        card
        for status in ("seed", "validated")
        for card in library.load(status)
    ]
    pool = [
        card
        for card in cards
        if card.role == role and card.phase in {"ANY", phase}
    ]
    pool.sort(key=lambda card: card.strategy_id)
    return [card.strategy_id for card in pool[:limit]]


def _keyword_retrieval(
    state: GameState,
    actor,
    library: StrategyLibrary,
    limit: int = 3,
) -> list[str]:
    context = build_context(state, actor)
    matches = library.search(
        context.text,
        role=context.role,
        phase=context.phase,
        limit=limit,
    )
    return [match.card.strategy_id for match in matches]


def _structured_retrieval(
    state: GameState,
    actor,
    library: StrategyLibrary,
    limit: int = 3,
) -> list[str]:
    matches = rank_tactics(state, actor, root=library.root, limit=limit)
    return [match.card.strategy_id for match in matches]


def _recall(hit: list[str], expected: tuple[str, ...]) -> float:
    if not expected:
        return 0.0
    found = len(set(hit) & set(expected))
    return found / len(expected)


def run_ablation(*, library_root: Path | None = None) -> dict:
    root = library_root or DEFAULT_LIBRARY_ROOT
    library = StrategyLibrary(root)
    rows = []
    totals = {"no_rag": 0.0, "keyword_rag": 0.0, "structured_rag": 0.0}
    for index, scenario in enumerate(SCENARIOS):
        state, actor = build_scenario_state(scenario, seed=9000 + index)
        no_rag = _no_retrieval(library, actor.role.value, state.phase.value)
        keyword_rag = _keyword_retrieval(state, actor, library)
        structured_rag = _structured_retrieval(state, actor, library)
        scores = {
            "no_rag": _recall(no_rag, scenario.expected),
            "keyword_rag": _recall(keyword_rag, scenario.expected),
            "structured_rag": _recall(structured_rag, scenario.expected),
        }
        for key, value in scores.items():
            totals[key] += value
        rows.append(
            {
                "scenario": scenario.name,
                "expected": list(scenario.expected),
                "no_rag": no_rag,
                "keyword_rag": keyword_rag,
                "structured_rag": structured_rag,
                "scores": scores,
            }
        )
    count = len(rows)
    return {
        "scenario_count": count,
        "rows": rows,
        "mean_recall": {
            key: round(value / count, 4) for key, value in totals.items()
        },
    }


def render_markdown(result: dict) -> str:
    lines = [
        "# RAG 消融实验：无检索 / 词法检索 / 结构化检索",
        "",
        f"固定局面数：{result['scenario_count']}。"
        "指标为 Recall@3：前 3 条命中人工标注期望战术的比例。",
        "",
        "| 局面 | 期望战术 | 无检索 | 词法检索 | 结构化检索 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in result["rows"]:
        lines.append(
            "| {scenario} | {expected} | {no_rag} | {keyword} | {structured} |".format(
                scenario=row["scenario"],
                expected=", ".join(row["expected"]),
                no_rag=f"{row['scores']['no_rag']:.2f}",
                keyword=f"{row['scores']['keyword_rag']:.2f}",
                structured=f"{row['scores']['structured_rag']:.2f}",
            )
        )
    mean = result["mean_recall"]
    lines.extend(
        [
            "",
            "## 汇总",
            "",
            f"- 无检索 Recall@3：**{mean['no_rag']:.3f}**",
            f"- 词法检索 Recall@3：**{mean['keyword_rag']:.3f}**",
            f"- 结构化检索 Recall@3：**{mean['structured_rag']:.3f}**",
            "",
            "结构化检索 = 角色/阶段过滤 + 审计信号 + 票型信号 + 词法重合，",
            "全程离线、确定性，不依赖任何外部 embedding 服务。",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render_markdown(run_ablation()))
