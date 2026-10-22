"""Core data structures and game creation for the WolfArena rules engine.

This first module only creates a game and assigns roles. Night actions, voting,
and winner calculation are implemented in later modules.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from random import Random
from typing import Final, Sequence


class Role(str, Enum):
    """Every role available in the nine-player game."""

    WEREWOLF = "werewolf"
    VILLAGER = "villager"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"


class Team(str, Enum):
    """The winning side to which a role belongs."""

    WOLF = "wolf"
    GOOD = "good"


class Phase(str, Enum):
    """The phases in which players are allowed to act."""

    INIT = "INIT"
    NIGHT = "NIGHT"
    DAY_DISCUSSION = "DAY_DISCUSSION"
    SELF_DESTRUCT = "SELF_DESTRUCT"
    VOTE = "VOTE"
    END = "END"


class EventType(str, Enum):
    """Stable event names used by the game log."""

    GAME_CREATED = "GAME_CREATED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    NIGHT_STARTED = "NIGHT_STARTED"


class Visibility(str, Enum):
    """The default audience for an event."""

    PUBLIC = "public"
    PLAYER = "player"
    WOLVES = "wolves"
    GOD = "god"


ROLE_DECK: Final[tuple[Role, ...]] = (
    Role.WEREWOLF,
    Role.WEREWOLF,
    Role.WEREWOLF,
    Role.VILLAGER,
    Role.VILLAGER,
    Role.VILLAGER,
    Role.SEER,
    Role.WITCH,
    Role.HUNTER,
)

ROLE_TO_TEAM: Final[dict[Role, Team]] = {
    Role.WEREWOLF: Team.WOLF,
    Role.VILLAGER: Team.GOOD,
    Role.SEER: Team.GOOD,
    Role.WITCH: Team.GOOD,
    Role.HUNTER: Team.GOOD,
}


@dataclass(slots=True)
class Player:
    """One seated player in a game."""

    player_id: str
    seat: int
    name: str
    role: Role
    is_human: bool
    is_alive: bool = True

    @property
    def team(self) -> Team:
        """Return the team from the player's private role."""

        return ROLE_TO_TEAM[self.role]


@dataclass(slots=True)
class NightResult:
    """Night-action results that can be filled in by the night engine."""

    wolf_target_id: str | None = None
    antidote_target_id: str | None = None
    poison_target_id: str | None = None
    hunter_target_id: str | None = None
    death_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Event:
    """A structured fact that happened during the game."""

    event_seq: int
    event_type: EventType
    day: int
    phase: Phase
    actor_id: str | None
    target_id: str | None
    visibility: Visibility
    visible_to: tuple[str, ...] = ()
    data: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class GameState:
    """All information needed to continue and audit one game."""

    seed: int
    players: list[Player]
    phase: Phase = Phase.INIT
    day: int = 0
    night_result: NightResult | None = None
    events: list[Event] = field(default_factory=list)

    def role_counts(self) -> Counter[Role]:
        """Return one count for each role in the game."""

        return Counter(player.role for player in self.players)


def create_game(
    seed: int,
    human_count: int = 1,
    player_names: Sequence[str] | None = None,
) -> GameState:
    """Create one nine-player game with a reproducible role assignment.

    Args:
        seed: Controls only the role shuffle. The same seed produces the same
            seat-to-role assignment.
        human_count: Number of human-controlled seats. P0 uses 1 to 3, while
            0 may be used later for AI-only training games.
        player_names: Optional names for seats 1 to 9. Defaults to 玩家1-玩家9.

    Raises:
        TypeError: If seed or human_count has an invalid type.
        ValueError: If human_count, player names, or the role deck is invalid.
    """

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed 必须是整数")
    if isinstance(human_count, bool) or not isinstance(human_count, int):
        raise TypeError("human_count 必须是整数")
    if not 0 <= human_count <= 9:
        raise ValueError("human_count 必须在 0 到 9 之间")

    names = (
        [f"玩家{seat}" for seat in range(1, 10)]
        if player_names is None
        else list(player_names)
    )
    if len(names) != 9:
        raise ValueError("player_names 必须包含 9 个名字")
    if any(not isinstance(name, str) or not name.strip() for name in names):
        raise ValueError("每个玩家名字必须是非空字符串")
    if len(set(names)) != 9:
        raise ValueError("九名玩家的名字必须互不相同")

    # A private Random instance avoids changing Python's global random state.
    rng = Random(seed)
    assigned_roles = list(ROLE_DECK)
    rng.shuffle(assigned_roles)

    role_counter = Counter(assigned_roles)
    expected_counter = Counter(ROLE_DECK)
    if len(assigned_roles) != 9 or role_counter != expected_counter:
        raise RuntimeError("角色牌堆校验失败")

    players = [
        Player(
            player_id=f"p{seat}",
            seat=seat,
            name=names[seat - 1],
            role=assigned_roles[seat - 1],
            is_human=seat <= human_count,
        )
        for seat in range(1, 10)
    ]

    events = [
        Event(
            event_seq=0,
            event_type=EventType.GAME_CREATED,
            day=0,
            phase=Phase.INIT,
            actor_id=None,
            target_id=None,
            visibility=Visibility.GOD,
            data={"seed": seed, "human_count": human_count},
        )
    ]
    for event_seq, player in enumerate(players, start=1):
        events.append(
            Event(
                event_seq=event_seq,
                event_type=EventType.ROLE_ASSIGNED,
                day=0,
                phase=Phase.INIT,
                actor_id=None,
                target_id=player.player_id,
                visibility=Visibility.PLAYER,
                visible_to=(player.player_id,),
                data={"role": player.role.value},
            )
        )

    return GameState(
        seed=seed,
        players=players,
        phase=Phase.INIT,
        day=0,
        night_result=None,
        events=events,
    )


def get_player(state: GameState, identifier: str) -> Player:
    """Find a player by player_id or unique nickname."""

    for player in state.players:
        if player.player_id == identifier or player.name == identifier:
            return player
    raise KeyError(f"找不到玩家：{identifier}")


def start_night(state: GameState) -> GameState:
    """Advance the game to the next night.

    The full night-action sequence is intentionally outside this milestone.
    This function only changes the day, phase, and empty night-result object.
    """

    allowed_previous_phases = {
        Phase.INIT,
        Phase.VOTE,
        Phase.SELF_DESTRUCT,
    }
    if state.phase not in allowed_previous_phases:
        raise ValueError(f"当前阶段不能开始夜晚：{state.phase.value}")

    state.day += 1
    state.phase = Phase.NIGHT
    state.night_result = NightResult()
    state.events.append(
        Event(
            event_seq=len(state.events),
            event_type=EventType.NIGHT_STARTED,
            day=state.day,
            phase=state.phase,
            actor_id=None,
            target_id=None,
            visibility=Visibility.PUBLIC,
            data={"day": state.day},
        )
    )
    return state


def check_winner(state: GameState) -> Team | None:
    """Return the winning team based only on living role counts.

    ``None`` means neither win condition is currently satisfied. Death and
    phase handling must call this function after every death event.
    """

    living_wolves = sum(
        player.is_alive and player.role is Role.WEREWOLF
        for player in state.players
    )
    living_good = sum(
        player.is_alive and player.role is not Role.WEREWOLF
        for player in state.players
    )

    if living_wolves == 0:
        return Team.GOOD
    if living_wolves >= living_good:
        return Team.WOLF
    return None
