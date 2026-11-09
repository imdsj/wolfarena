"""Public vote-history analysis for AI reasoning.

Only final ``VOTE_RESULT`` events are read, so a player never sees another
player's private ballot before the tally is public. The output is plain text
that can be injected into a speech prompt or read by a rule policy.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from .game_engine import EventType, GameState, Player, get_visible_events


VoteHistory = dict[int, dict[int, int | None]]


def vote_history(state: GameState, viewer: Player) -> VoteHistory:
    """Return day -> {voter seat: target seat or None for abstain}."""

    seat_by_id = {
        player.player_id: player.seat for player in state.players
    }
    history: VoteHistory = {}
    for event in get_visible_events(state, viewer):
        if event.event_type is not EventType.VOTE_RESULT:
            continue
        raw_votes = event.data.get("votes")
        if not isinstance(raw_votes, dict):
            continue
        row: dict[int, int | None] = {}
        for voter_id, target_id in raw_votes.items():
            voter = seat_by_id.get(str(voter_id))
            if voter is None:
                continue
            target = seat_by_id.get(str(target_id)) if target_id else None
            row[voter] = target
        if row:
            history[int(event.day)] = row
    return history


def same_vote_blocks(
    history: VoteHistory,
    *,
    min_days: int = 2,
) -> list[tuple[int, int, int]]:
    """Seat pairs that voted the same non-abstain target on >= min_days."""

    together: dict[tuple[int, int], int] = defaultdict(int)
    for row in history.values():
        seats = sorted(row)
        for index, left in enumerate(seats):
            for right in seats[index + 1 :]:
                target = row.get(left)
                if target is None or target != row.get(right):
                    continue
                together[(left, right)] += 1
    blocks = [
        (left, right, days)
        for (left, right), days in together.items()
        if days >= min_days
    ]
    blocks.sort(key=lambda item: (-item[2], item[0], item[1]))
    return blocks


def consensus_defectors(history: VoteHistory) -> Counter:
    """Count days a voter did not follow the day's plurality target."""

    defectors: Counter = Counter()
    for row in history.values():
        counts = Counter(
            target for target in row.values() if target is not None
        )
        if not counts:
            continue
        highest = max(counts.values())
        leaders = {
            target for target, count in counts.items() if count == highest
        }
        if len(leaders) != 1:
            continue
        leader = next(iter(leaders))
        for voter, target in row.items():
            if target is not None and target != leader:
                defectors[voter] += 1
    return defectors


def format_vote_history(history: VoteHistory, *, limit: int = 3) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for day in sorted(history)[-limit:]:
        row = history[day]
        parts = [
            f"{voter}→{target}" if target is not None else f"{voter}→弃权"
            for voter, target in sorted(row.items())
        ]
        lines.append(f"第{day}天：" + "、".join(parts))
    return "\n".join(lines)


def format_vote_analysis(
    state: GameState,
    viewer: Player,
    *,
    limit: int = 3,
) -> str:
    """A compact, public-information-only vote analysis block."""

    history = vote_history(state, viewer)
    if not history:
        return ""
    lines = [format_vote_history(history, limit=limit)]
    blocks = same_vote_blocks(history)
    if blocks:
        lines.append(
            "连续同票："
            + "；".join(
                f"{left}号与{right}号连续{days}天同票"
                for left, right, days in blocks[:5]
            )
        )
    defectors = consensus_defectors(history)
    if defectors:
        lines.append(
            "未跟最高票："
            + "、".join(
                f"{seat}号{count}天"
                for seat, count in defectors.most_common(5)
            )
        )
    return "\n".join(lines)
