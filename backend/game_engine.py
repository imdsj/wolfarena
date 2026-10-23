"""Core data structures and game creation for the WolfArena rules engine.

This first module only creates a game and assigns roles. Night actions, voting,
and winner calculation are implemented in later modules.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from enum import Enum
from random import Random
from typing import Final, Mapping, Sequence


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
    NIGHT_WOLF_DISCUSSION_R1 = "NIGHT_WOLF_DISCUSSION_R1"
    NIGHT_WOLF_DISCUSSION_R2 = "NIGHT_WOLF_DISCUSSION_R2"
    NIGHT_WOLF_KILL = "NIGHT_WOLF_KILL"
    NIGHT_SEER_CHECK = "NIGHT_SEER_CHECK"
    NIGHT_WITCH_ACTION = "NIGHT_WITCH_ACTION"
    NIGHT_RESOLUTION = "NIGHT_RESOLUTION"
    NIGHT_HUNTER_SHOT = "NIGHT_HUNTER_SHOT"
    DAY_ANNOUNCEMENT = "DAY_ANNOUNCEMENT"
    DAY_LAST_WORDS = "DAY_LAST_WORDS"
    DAY_DISCUSSION = "DAY_DISCUSSION"
    SELF_DESTRUCT = "SELF_DESTRUCT"
    VOTE = "VOTE"
    DAY_HUNTER_SHOT = "DAY_HUNTER_SHOT"
    END = "END"


class EventType(str, Enum):
    """Stable event names used by the game log."""

    GAME_CREATED = "GAME_CREATED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    WOLF_CAPTAIN_ELECTED = "WOLF_CAPTAIN_ELECTED"
    WOLF_SPEECH = "WOLF_SPEECH"
    WOLF_KILL_SELECTED = "WOLF_KILL_SELECTED"
    SEER_CHECKED = "SEER_CHECKED"
    WITCH_USED_ANTIDOTE = "WITCH_USED_ANTIDOTE"
    WITCH_USED_POISON = "WITCH_USED_POISON"
    PLAYER_DIED = "PLAYER_DIED"
    HUNTER_SHOT = "HUNTER_SHOT"
    SELF_DESTRUCTED = "SELF_DESTRUCTED"
    VOTE_CAST = "VOTE_CAST"
    WINNER_DECIDED = "WINNER_DECIDED"
    NIGHT_STARTED = "NIGHT_STARTED"


class Visibility(str, Enum):
    """The default audience for an event."""

    PUBLIC = "public"
    PLAYER = "player"
    WOLVES = "wolves"
    GOD = "god"


PHASE_ORDER: Final[tuple[Phase, ...]] = (
    Phase.INIT,
    Phase.NIGHT_WOLF_DISCUSSION_R1,
    Phase.NIGHT_WOLF_DISCUSSION_R2,
    Phase.NIGHT_WOLF_KILL,
    Phase.NIGHT_SEER_CHECK,
    Phase.NIGHT_WITCH_ACTION,
    Phase.NIGHT_RESOLUTION,
    Phase.NIGHT_HUNTER_SHOT,
    Phase.DAY_ANNOUNCEMENT,
    Phase.DAY_LAST_WORDS,
    Phase.DAY_DISCUSSION,
    Phase.SELF_DESTRUCT,
    Phase.VOTE,
    Phase.DAY_HUNTER_SHOT,
    Phase.END,
)

SPECTATOR_VIEW: Final[str] = "spectator"


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
    wolf_kill_submitted: bool = False
    wolf_kill_type: str | None = None
    seer_target_id: str | None = None
    seer_result: str | None = None
    witch_action_submitted: bool = False
    antidote_target_id: str | None = None
    poison_target_id: str | None = None
    hunter_target_id: str | None = None
    hunter_can_shoot: bool = False
    resolved: bool = False
    death_ids: list[str] = field(default_factory=list)
    death_causes: dict[str, list[str]] = field(default_factory=dict)


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
    wolf_captain_id: str | None = None
    antidote_available: bool = True
    poison_available: bool = True
    phase: Phase = Phase.INIT
    day: int = 0
    night_result: NightResult | None = None
    events: list[Event] = field(default_factory=list)

    def role_counts(self) -> Counter[Role]:
        """Return one count for each role in the game."""

        return Counter(player.role for player in self.players)


def append_event(
    state: GameState,
    event_type: EventType,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    visibility: Visibility = Visibility.PUBLIC,
    visible_to: Sequence[str] = (),
    data: Mapping[str, object] | None = None,
) -> Event:
    """Append one event while enforcing a contiguous event sequence."""

    expected_seq = len(state.events)
    if state.events and state.events[-1].event_seq != expected_seq - 1:
        raise ValueError("事件序号必须从 0 开始连续递增")

    event = Event(
        event_seq=expected_seq,
        event_type=event_type,
        day=state.day,
        phase=state.phase,
        actor_id=actor_id,
        target_id=target_id,
        visibility=visibility,
        visible_to=tuple(dict.fromkeys(visible_to)),
        data=dict(data or {}),
    )
    state.events.append(event)
    return event


def create_game(
    seed: int,
    human_count: int = 1,
    player_names: Sequence[str] | None = None,
) -> GameState:
    """Create one nine-player game with a reproducible role assignment.

    Args:
        seed: Controls only the role shuffle. The same seed produces the same
            seat-to-role assignment.
        human_count: Number of human-controlled seats. P0 user games allow
            1 to 3 (GAME-004); 0 is reserved for AI-only training games.
        player_names: Optional names for seats 1 to 9. Defaults to 玩家1-玩家9.

    Raises:
        TypeError: If seed or human_count has an invalid type.
        ValueError: If human_count, player names, or the role deck is invalid.
    """

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("seed 必须是整数")
    if isinstance(human_count, bool) or not isinstance(human_count, int):
        raise TypeError("human_count 必须是整数")
    # GAME-004 allows 1 to 3 human players in P0 games. Zero is reserved
    # for AI-only training, while 4 to 9 have no valid game mode.
    if human_count != 0 and not 1 <= human_count <= 3:
        raise ValueError("human_count 必须为 0（AI-only）或 1 至 3")

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

    state = GameState(
        seed=seed,
        players=players,
        phase=Phase.INIT,
        day=0,
        night_result=None,
    )
    append_event(
        state,
        EventType.GAME_CREATED,
        visibility=Visibility.GOD,
        data={"seed": seed, "human_count": human_count},
    )
    for player in players:
        is_wolf = player.role is Role.WEREWOLF
        append_event(
            state,
            EventType.ROLE_ASSIGNED,
            target_id=player.player_id,
            visibility=Visibility.WOLVES if is_wolf else Visibility.PLAYER,
            visible_to=() if is_wolf else (player.player_id,),
            data={"role": player.role.value},
        )

    return state


def _living_players_with_role(state: GameState, role: Role) -> list[Player]:
    return sorted(
        (
            player
            for player in state.players
            if player.role is role and player.is_alive
        ),
        key=lambda player: player.seat,
    )


def _night_result_or_error(state: GameState) -> NightResult:
    if state.night_result is None:
        raise ValueError("当前没有进行中的夜间结果")
    return state.night_result


def elect_wolf_captain(
    state: GameState,
    captain_id: str | None = None,
) -> GameState:
    """Elect a living wolf captain according to the confirmed captain rules."""

    if state.phase not in {
        Phase.INIT,
        Phase.NIGHT_WOLF_DISCUSSION_R1,
    }:
        raise ValueError(f"当前阶段不能选择狼队长：{state.phase.value}")

    living_wolves = _living_players_with_role(state, Role.WEREWOLF)
    if not living_wolves:
        raise ValueError("没有存活的狼人可以选择")

    if state.wolf_captain_id is not None:
        current = get_player(state, state.wolf_captain_id)
        if current.is_alive:
            raise ValueError("存活狼队长已经存在")

    human_wolves = [player for player in living_wolves if player.is_human]
    if captain_id is not None:
        requested = get_player(state, captain_id)
        if requested not in living_wolves:
            raise ValueError("狼队长必须是存活的狼人")
        if human_wolves and requested not in human_wolves:
            raise ValueError("狼队存在真人时，狼队长必须是真人狼人")
        captain = requested
        selection_method = "manual"
    elif len(human_wolves) == 1:
        captain = human_wolves[0]
        selection_method = "only_human"
    else:
        candidates = human_wolves or living_wolves
        rng = Random(f"{state.seed}:{state.day}:wolf-captain")
        captain = rng.choice(candidates)
        selection_method = "seed_random"

    state.wolf_captain_id = captain.player_id
    append_event(
        state,
        EventType.WOLF_CAPTAIN_ELECTED,
        target_id=captain.player_id,
        visibility=Visibility.WOLVES,
        data={
            "captain_id": captain.player_id,
            "day": state.day,
            "selection": selection_method,
        },
    )
    return state


def record_wolf_speech(
    state: GameState,
    actor_id: str,
    round_number: int,
    content: str,
) -> GameState:
    """Record one ordered wolf-team speech and advance speech phases."""

    actor = get_player(state, actor_id)
    if actor.role is not Role.WEREWOLF:
        raise ValueError("只有狼人可以提交狼人发言")
    if not actor.is_alive:
        raise ValueError("死亡狼人不能发言")

    expected_phase = {
        1: Phase.NIGHT_WOLF_DISCUSSION_R1,
        2: Phase.NIGHT_WOLF_DISCUSSION_R2,
    }.get(round_number)
    if expected_phase is None:
        raise ValueError("狼人发言轮次只能是 1 或 2")
    if state.phase is not expected_phase:
        raise ValueError(
            f"第 {round_number} 轮狼人发言不能在 {state.phase.value} 阶段提交"
        )

    captain_id = state.wolf_captain_id
    if captain_id is None or not get_player(state, captain_id).is_alive:
        raise ValueError("当前没有存活的狼队长")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("狼人发言内容不能为空")

    _night_result_or_error(state)
    living_wolves = _living_players_with_role(state, Role.WEREWOLF)
    spoken_ids = {
        event.actor_id
        for event in state.events
        if event.event_type is EventType.WOLF_SPEECH
        and event.day == state.day
        and event.data.get("round") == round_number
    }
    if actor.player_id in spoken_ids:
        raise ValueError("该狼人本轮已经发言")

    expected_actor = next(
        (
            player
            for player in living_wolves
            if player.player_id not in spoken_ids
        ),
        None,
    )
    if expected_actor is None or actor.player_id != expected_actor.player_id:
        raise ValueError("狼人必须按照存活狼人的座次顺序发言")

    append_event(
        state,
        EventType.WOLF_SPEECH,
        actor_id=actor.player_id,
        visibility=Visibility.WOLVES,
        data={"round": round_number, "content": content.strip()},
    )

    spoken_ids.add(actor.player_id)
    if len(spoken_ids) == len(living_wolves):
        state.phase = (
            Phase.NIGHT_WOLF_DISCUSSION_R2
            if round_number == 1
            else Phase.NIGHT_WOLF_KILL
        )
    return state


def select_wolf_kill(
    state: GameState,
    actor_id: str,
    target_id: str | None,
) -> GameState:
    """Record the wolf captain's single kill decision for this night."""

    actor = get_player(state, actor_id)
    if not actor.is_alive or actor.role is not Role.WEREWOLF:
        raise ValueError("只有存活狼人可以提交狼刀")
    if state.phase is not Phase.NIGHT_WOLF_KILL:
        raise ValueError(f"当前阶段不能提交狼刀：{state.phase.value}")
    if state.wolf_captain_id != actor.player_id:
        raise ValueError("只有狼队长可以提交狼刀")

    night_result = _night_result_or_error(state)
    if night_result.wolf_kill_submitted:
        raise ValueError("本夜狼刀已经提交")

    if target_id is None:
        kill_type = "empty"
    else:
        target = get_player(state, target_id)
        if not target.is_alive:
            raise ValueError("狼刀目标必须存活")
        kill_type = "self" if target.player_id == actor.player_id else "target"
        night_result.wolf_target_id = target.player_id

    night_result.wolf_kill_submitted = True
    night_result.wolf_kill_type = kill_type
    append_event(
        state,
        EventType.WOLF_KILL_SELECTED,
        actor_id=actor.player_id,
        target_id=night_result.wolf_target_id,
        visibility=Visibility.WOLVES,
        data={"kill_type": kill_type},
    )

    if _living_players_with_role(state, Role.SEER):
        state.phase = Phase.NIGHT_SEER_CHECK
    elif _living_players_with_role(state, Role.WITCH):
        state.phase = Phase.NIGHT_WITCH_ACTION
    else:
        state.phase = Phase.NIGHT_RESOLUTION
    return state


def submit_seer_check(
    state: GameState,
    actor_id: str,
    target_id: str,
) -> Team:
    """Check one living target and return the target's team."""

    actor = get_player(state, actor_id)
    if not actor.is_alive or actor.role is not Role.SEER:
        raise ValueError("只有存活预言家可以查验")
    if state.phase is not Phase.NIGHT_SEER_CHECK:
        raise ValueError(f"当前阶段不能查验：{state.phase.value}")

    target = get_player(state, target_id)
    if not target.is_alive:
        raise ValueError("查验目标必须存活")
    if target.player_id == actor.player_id:
        raise ValueError("预言家不能查验自己")

    night_result = _night_result_or_error(state)
    if night_result.seer_target_id is not None:
        raise ValueError("本夜预言家已经完成查验")

    result = Team.WOLF if target.role is Role.WEREWOLF else Team.GOOD
    night_result.seer_target_id = target.player_id
    night_result.seer_result = result.value
    append_event(
        state,
        EventType.SEER_CHECKED,
        actor_id=actor.player_id,
        target_id=target.player_id,
        visibility=Visibility.PLAYER,
        visible_to=(actor.player_id,),
        data={"result": result.value},
    )

    if _living_players_with_role(state, Role.WITCH):
        state.phase = Phase.NIGHT_WITCH_ACTION
    else:
        state.phase = Phase.NIGHT_RESOLUTION
    return result


def get_witch_kill_target(state: GameState, actor_id: str) -> str | None:
    """Return the wolf target only while the witch still has the antidote."""

    actor = get_player(state, actor_id)
    if not actor.is_alive or actor.role is not Role.WITCH:
        raise ValueError("只有存活女巫可以查看刀口")
    if state.phase is not Phase.NIGHT_WITCH_ACTION:
        raise ValueError(f"当前阶段不能查看刀口：{state.phase.value}")
    night_result = _night_result_or_error(state)
    if not state.antidote_available:
        return None
    return night_result.wolf_target_id


def submit_witch_action(
    state: GameState,
    actor_id: str,
    action: str,
    target_id: str | None = None,
) -> GameState:
    """Submit one witch action: antidote, poison, or no potion."""

    actor = get_player(state, actor_id)
    if not actor.is_alive or actor.role is not Role.WITCH:
        raise ValueError("只有存活女巫可以提交女巫行动")
    if state.phase is not Phase.NIGHT_WITCH_ACTION:
        raise ValueError(f"当前阶段不能提交女巫行动：{state.phase.value}")

    night_result = _night_result_or_error(state)
    if night_result.witch_action_submitted:
        raise ValueError("女巫本夜已经提交行动")

    normalized_action = action.strip().lower()
    if normalized_action not in {"antidote", "poison", "none"}:
        raise ValueError("女巫行动必须是 antidote、poison 或 none")

    if normalized_action == "none":
        if target_id is not None:
            raise ValueError("不使用药时不能指定目标")
    else:
        if target_id is None:
            raise ValueError("救人或毒人必须指定目标")
        target = get_player(state, target_id)
        if not target.is_alive:
            raise ValueError("女巫用药目标必须存活")

        if normalized_action == "antidote":
            if not state.antidote_available:
                raise ValueError("解药已经使用")
            state.antidote_available = False
            night_result.antidote_target_id = target.player_id
            append_event(
                state,
                EventType.WITCH_USED_ANTIDOTE,
                actor_id=actor.player_id,
                target_id=target.player_id,
                visibility=Visibility.PLAYER,
                visible_to=(actor.player_id,),
            )
        else:
            if not state.poison_available:
                raise ValueError("毒药已经使用")
            state.poison_available = False
            night_result.poison_target_id = target.player_id
            append_event(
                state,
                EventType.WITCH_USED_POISON,
                actor_id=actor.player_id,
                target_id=target.player_id,
                visibility=Visibility.PLAYER,
                visible_to=(actor.player_id,),
            )

    night_result.witch_action_submitted = True
    state.phase = Phase.NIGHT_RESOLUTION
    return state


def resolve_night(state: GameState) -> GameState:
    """Resolve wolf kill and poison once, then apply deaths and winner checks."""

    if state.phase is not Phase.NIGHT_RESOLUTION:
        raise ValueError(f"当前阶段不能结算夜晚：{state.phase.value}")
    night_result = _night_result_or_error(state)
    if night_result.resolved:
        raise ValueError("本夜已经完成结算")
    if not night_result.wolf_kill_submitted:
        raise ValueError("狼队长尚未提交狼刀")

    living_witches = _living_players_with_role(state, Role.WITCH)
    if living_witches and not night_result.witch_action_submitted:
        raise ValueError("存活女巫尚未提交本夜行动")

    causes_by_player: dict[str, list[str]] = {}
    wolf_target_id = night_result.wolf_target_id
    if (
        wolf_target_id is not None
        and wolf_target_id != night_result.antidote_target_id
    ):
        causes_by_player.setdefault(wolf_target_id, []).append("wolf_kill")
    if night_result.poison_target_id is not None:
        causes_by_player.setdefault(night_result.poison_target_id, []).append(
            "poisoned"
        )

    death_ids = sorted(
        causes_by_player,
        key=lambda player_id: get_player(state, player_id).seat,
    )
    for player_id in death_ids:
        player = get_player(state, player_id)
        causes = causes_by_player[player_id]
        player.is_alive = False
        append_event(
            state,
            EventType.PLAYER_DIED,
            target_id=player_id,
            visibility=Visibility.PUBLIC,
            data={"causes": list(causes)},
        )

    night_result.death_ids = list(death_ids)
    night_result.death_causes = {
        player_id: list(causes)
        for player_id, causes in causes_by_player.items()
    }
    night_result.resolved = True

    hunter = next(
        (player for player in state.players if player.role is Role.HUNTER),
        None,
    )
    hunter_causes = (
        night_result.death_causes.get(hunter.player_id, [])
        if hunter is not None
        else []
    )
    night_result.hunter_can_shoot = (
        "wolf_kill" in hunter_causes and "poisoned" not in hunter_causes
    )
    if night_result.hunter_can_shoot:
        state.phase = Phase.NIGHT_HUNTER_SHOT
        return state

    winner = check_winner(state)
    if winner is None:
        state.phase = Phase.DAY_ANNOUNCEMENT
        return state

    state.phase = Phase.END
    append_event(
        state,
        EventType.WINNER_DECIDED,
        visibility=Visibility.PUBLIC,
        data={"winner": winner.value, "reason": "night_resolution"},
    )
    return state


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
    state.phase = Phase.NIGHT_WOLF_DISCUSSION_R1
    state.night_result = NightResult()
    append_event(
        state,
        EventType.NIGHT_STARTED,
        visibility=Visibility.PUBLIC,
        data={"day": state.day},
    )
    return state


def get_visible_events(
    state: GameState,
    viewer: Player | str,
) -> tuple[Event, ...]:
    """Return events visible to a player or to the authenticated spectator."""

    if viewer == SPECTATOR_VIEW:
        return tuple(state.events)

    player = viewer if isinstance(viewer, Player) else get_player(state, viewer)
    if not any(candidate is player for candidate in state.players):
        raise ValueError("玩家不属于当前游戏")
    if state.phase is Phase.END:
        return tuple(state.events)

    visible_events: list[Event] = []
    for event in state.events:
        if event.visibility is Visibility.PUBLIC:
            if event.event_type is EventType.PLAYER_DIED:
                data = dict(event.data)
                data.pop("causes", None)
                visible_events.append(replace(event, data=data))
            else:
                visible_events.append(event)
        elif (
            event.visibility is Visibility.PLAYER
            and player.player_id in event.visible_to
        ):
            visible_events.append(event)
        elif (
            event.visibility is Visibility.WOLVES
            and player.is_alive
            and player.role is Role.WEREWOLF
        ):
            visible_events.append(event)

    return tuple(visible_events)


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
