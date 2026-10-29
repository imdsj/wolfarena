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
    PLAYER_JOINED = "PLAYER_JOINED"
    ROLE_ASSIGNED = "ROLE_ASSIGNED"
    AI_FALLBACK_USED = "AI_FALLBACK_USED"
    AI_ACTION_REJECTED = "AI_ACTION_REJECTED"
    AI_ACTION_FAILED = "AI_ACTION_FAILED"
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
    VOTE_CLOSED = "VOTE_CLOSED"
    VOTE_RESULT = "VOTE_RESULT"
    BANISHMENT_LAST_WORDS_STARTED = "BANISHMENT_LAST_WORDS_STARTED"
    PUBLIC_SPEECH = "PUBLIC_SPEECH"
    PUBLIC_SPEECH_TIMEOUT = "PUBLIC_SPEECH_TIMEOUT"
    LAST_WORDS = "LAST_WORDS"
    LAST_WORDS_TIMEOUT = "LAST_WORDS_TIMEOUT"
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
PUBLIC_SPEECH_TIMEOUT_SECONDS: Final[float] = 30.0
LAST_WORDS_TIMEOUT_SECONDS: Final[float] = 30.0
HUMAN_ACTION_TIMEOUT_SECONDS: Final[float] = 20.0


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


@dataclass(slots=True)
class DayResult:
    """State for the current public day."""

    announced_death_ids: list[str] = field(default_factory=list)
    last_words_queue: list[str] = field(default_factory=list)
    last_words_done: list[str] = field(default_factory=list)
    last_words_timeout_seconds: float = LAST_WORDS_TIMEOUT_SECONDS
    last_words_deadline: float | None = None
    speech_order: list[str] = field(default_factory=list)
    next_speaker_index: int = 0
    speech_timeout_seconds: float = PUBLIC_SPEECH_TIMEOUT_SECONDS
    speech_deadline: float | None = None
    self_destruct_ids: list[str] = field(default_factory=list)
    self_destruct_deadline: float | None = None
    votes: dict[str, str | None] = field(default_factory=dict)
    votes_closed: bool = False
    vote_resolved: bool = False
    banished_id: str | None = None
    banishment_pending: bool = False
    day_hunter_can_shoot: bool = False
    day_hunter_target_id: str | None = None
    death_causes: dict[str, list[str]] = field(default_factory=dict)
    after_last_words_phase: Phase | None = None
    resolved: bool = False


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
    day_speech_starter_id: str | None = None
    night_result: NightResult | None = None
    day_result: DayResult | None = None
    events: list[Event] = field(default_factory=list)
    phase_deadline_at: float | None = None
    phase_deadline_kind: str | None = None

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


def _choose_wolf_captain(
    state: GameState,
    captain_id: str | None,
    selection_day: int,
) -> tuple[Player, str]:
    living_wolves = _living_players_with_role(state, Role.WEREWOLF)
    if not living_wolves:
        raise ValueError("没有存活的狼人可以选择")

    human_wolves = [player for player in living_wolves if player.is_human]
    if captain_id is not None:
        requested = get_player(state, captain_id)
        if requested not in living_wolves:
            raise ValueError("狼队长必须是存活的狼人")
        if human_wolves and requested not in human_wolves:
            raise ValueError("狼队存在真人时，狼队长必须是真人狼人")
        return requested, "manual"
    if len(human_wolves) == 1:
        return human_wolves[0], "only_human"

    candidates = human_wolves or living_wolves
    rng = Random(f"{state.seed}:{selection_day}:wolf-captain")
    return rng.choice(candidates), "seed_random"


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

    captain, selection_method = _choose_wolf_captain(
        state,
        captain_id,
        state.day,
    )

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


def submit_night_hunter_shot(
    state: GameState,
    actor_id: str,
    target_id: str | None,
) -> GameState:
    """Resolve the night hunter's optional shot."""

    actor = get_player(state, actor_id)
    if actor.role is not Role.HUNTER:
        raise ValueError("只有猎人可以提交猎人开枪")
    if state.phase is not Phase.NIGHT_HUNTER_SHOT:
        raise ValueError(f"当前阶段不能进行夜间猎人开枪：{state.phase.value}")

    night_result = _night_result_or_error(state)
    if not night_result.hunter_can_shoot:
        raise ValueError("当前猎人没有夜间开枪资格")

    if target_id is not None:
        target = get_player(state, target_id)
        if not target.is_alive:
            raise ValueError("猎人开枪目标必须存活")

    night_result.hunter_can_shoot = False
    night_result.hunter_target_id = target_id
    append_event(
        state,
        EventType.HUNTER_SHOT,
        actor_id=actor.player_id,
        target_id=target_id,
        visibility=Visibility.PLAYER,
        visible_to=(actor.player_id,),
        data={"night": True},
    )

    if target_id is not None:
        target = get_player(state, target_id)
        target.is_alive = False
        causes = night_result.death_causes.setdefault(target_id, [])
        if "hunter_shot" not in causes:
            causes.append("hunter_shot")
        if target_id not in night_result.death_ids:
            night_result.death_ids.append(target_id)
            night_result.death_ids.sort(
                key=lambda player_id: get_player(state, player_id).seat
            )
        append_event(
            state,
            EventType.PLAYER_DIED,
            target_id=target_id,
            visibility=Visibility.PUBLIC,
            data={"causes": list(causes)},
        )

    winner = check_winner(state)
    if winner is None:
        state.phase = Phase.DAY_ANNOUNCEMENT
        return state

    state.phase = Phase.END
    append_event(
        state,
        EventType.WINNER_DECIDED,
        visibility=Visibility.PUBLIC,
        data={"winner": winner.value, "reason": "night_hunter_shot"},
    )
    return state


def _day_result_or_error(state: GameState) -> DayResult:
    if state.day_result is None:
        raise ValueError("当前没有进行中的白天结果")
    return state.day_result


def _living_speech_order(state: GameState) -> list[str]:
    return [
        player.player_id
        for player in sorted(state.players, key=lambda item: item.seat)
        if player.is_alive
    ]


def _public_speech_order(
    state: GameState,
    announced_death_ids: Sequence[str],
) -> list[str]:
    """Build one cyclic speaking round from the confirmed daytime rule."""

    living_players = [
        player
        for player in sorted(state.players, key=lambda item: item.seat)
        if player.is_alive
    ]
    if not living_players:
        return []

    if announced_death_ids:
        highest_dead_seat = max(
            get_player(state, player_id).seat
            for player_id in announced_death_ids
        )
        start_seat = highest_dead_seat % len(state.players) + 1
    elif state.day_speech_starter_id is not None:
        start_seat = get_player(state, state.day_speech_starter_id).seat
    else:
        start_seat = 1

    cyclic_players = sorted(
        living_players,
        key=lambda player: (player.seat - start_seat) % len(state.players),
    )
    return [player.player_id for player in cyclic_players]


def _finish_day(state: GameState, reason: str) -> GameState:
    day_result = _day_result_or_error(state)
    day_result.resolved = True
    winner = check_winner(state)
    if winner is None:
        return start_night(state)

    state.phase = Phase.END
    append_event(
        state,
        EventType.WINNER_DECIDED,
        visibility=Visibility.PUBLIC,
        data={"winner": winner.value, "reason": reason},
    )
    return state


def _next_living_speaker_index(
    state: GameState,
    start_index: int,
) -> int:
    day_result = _day_result_or_error(state)
    index = start_index
    while (
        index < len(day_result.speech_order)
        and not get_player(
            state,
            day_result.speech_order[index],
        ).is_alive
    ):
        index += 1
    return index


def _arm_public_speech_timer(
    state: GameState,
    now: float | None,
) -> None:
    day_result = _day_result_or_error(state)
    day_result.next_speaker_index = _next_living_speaker_index(
        state,
        day_result.next_speaker_index,
    )

    if day_result.next_speaker_index >= len(day_result.speech_order):
        day_result.speech_deadline = None
        state.phase = Phase.VOTE
        return

    day_result.speech_deadline = (
        None
        if now is None
        else now + day_result.speech_timeout_seconds
    )


def begin_day(
    state: GameState,
    *,
    now: float | None = None,
) -> GameState:
    """Create the public day context from the completed night."""

    if state.phase is not Phase.DAY_ANNOUNCEMENT:
        raise ValueError(f"当前阶段不能开始白天：{state.phase.value}")
    if state.day_result is not None and not state.day_result.resolved:
        raise ValueError("当前白天已经开始")

    announced_death_ids = (
        list(state.night_result.death_ids)
        if state.night_result is not None
        else []
    )
    day_result = DayResult(
        announced_death_ids=announced_death_ids,
        speech_timeout_seconds=PUBLIC_SPEECH_TIMEOUT_SECONDS,
    )
    day_result.speech_order = _public_speech_order(
        state,
        announced_death_ids,
    )
    if day_result.speech_order:
        state.day_speech_starter_id = day_result.speech_order[0]
    state.day_result = day_result

    if state.day == 1 and announced_death_ids:
        day_result.last_words_queue = list(announced_death_ids)
        day_result.after_last_words_phase = Phase.DAY_DISCUSSION
        state.phase = Phase.DAY_LAST_WORDS
        day_result.last_words_deadline = (
            None if now is None else now + LAST_WORDS_TIMEOUT_SECONDS
        )
        return state

    state.phase = Phase.DAY_DISCUSSION
    _arm_public_speech_timer(state, now)
    return state


def submit_last_words(
    state: GameState,
    actor_id: str,
    content: str,
    *,
    now: float | None = None,
) -> GameState:
    """Record one queued player's last words."""

    actor = get_player(state, actor_id)
    if actor.is_alive:
        raise ValueError("只有死亡玩家可以提交遗言")
    if state.phase is not Phase.DAY_LAST_WORDS:
        raise ValueError(f"当前阶段不能提交遗言：{state.phase.value}")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("遗言内容不能为空")
    normalized_content = content.strip()
    han_character_count = sum(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in normalized_content
    )
    if han_character_count > 100:
        raise ValueError("遗言中的汉字不能超过100个")

    day_result = _day_result_or_error(state)
    if not day_result.last_words_queue or (
        day_result.last_words_queue[0] != actor.player_id
    ):
        raise ValueError("该玩家当前没有遗言资格")

    append_event(
        state,
        EventType.LAST_WORDS,
        actor_id=actor.player_id,
        visibility=Visibility.PUBLIC,
        data={"content": normalized_content},
    )
    day_result.last_words_queue.pop(0)
    day_result.last_words_done.append(actor.player_id)

    if day_result.last_words_queue:
        day_result.last_words_deadline = (
            None if now is None else now + LAST_WORDS_TIMEOUT_SECONDS
        )
        return state
    day_result.last_words_deadline = None
    next_phase = day_result.after_last_words_phase
    day_result.after_last_words_phase = None
    if next_phase is None:
        return _finish_day(state, "day_last_words_complete")
    state.phase = next_phase
    if next_phase is Phase.DAY_DISCUSSION:
        _arm_public_speech_timer(state, now)
    return state


def timeout_last_words(state: GameState, now: float) -> GameState:
    """Expire the current player's 30-second last-words turn."""

    if state.phase is not Phase.DAY_LAST_WORDS:
        raise ValueError(f"当前阶段没有遗言：{state.phase.value}")
    day_result = _day_result_or_error(state)
    if day_result.last_words_deadline is None:
        raise ValueError("当前遗言没有可校验的截止时间")
    if now < day_result.last_words_deadline:
        raise ValueError("遗言时间尚未结束")
    if not day_result.last_words_queue:
        raise ValueError("当前没有等待中的遗言")

    actor_id = day_result.last_words_queue.pop(0)
    day_result.last_words_done.append(actor_id)
    append_event(
        state,
        EventType.LAST_WORDS_TIMEOUT,
        actor_id=actor_id,
        visibility=Visibility.PUBLIC,
        data={"deadline": day_result.last_words_deadline},
    )
    if day_result.last_words_queue:
        day_result.last_words_deadline = now + LAST_WORDS_TIMEOUT_SECONDS
        return state

    day_result.last_words_deadline = None
    next_phase = day_result.after_last_words_phase
    day_result.after_last_words_phase = None
    if next_phase is None:
        return _finish_day(state, "last_words_timeout_complete")
    state.phase = next_phase
    if next_phase is Phase.DAY_DISCUSSION:
        _arm_public_speech_timer(state, now)
    return state


def record_public_speech(
    state: GameState,
    actor_id: str,
    content: str,
    *,
    now: float | None = None,
) -> GameState:
    """Record one public speech in seat order."""

    actor = get_player(state, actor_id)
    if not actor.is_alive:
        raise ValueError("死亡玩家不能公开发言")
    if state.phase is not Phase.DAY_DISCUSSION:
        raise ValueError(f"当前阶段不能公开发言：{state.phase.value}")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("公开发言内容不能为空")

    day_result = _day_result_or_error(state)
    current_index = _next_living_speaker_index(
        state,
        day_result.next_speaker_index,
    )
    if current_index >= len(day_result.speech_order):
        raise ValueError("当前没有等待中的发言者")

    expected_id = day_result.speech_order[current_index]
    if actor.player_id != expected_id:
        raise ValueError("公开发言必须按照存活玩家座次进行")

    append_event(
        state,
        EventType.PUBLIC_SPEECH,
        actor_id=actor.player_id,
        visibility=Visibility.PUBLIC,
        data={"content": content.strip()},
    )
    day_result.next_speaker_index = current_index + 1
    _arm_public_speech_timer(state, now)
    return state


def timeout_public_speech(state: GameState, now: float) -> GameState:
    """Skip the current speaker after the server-side deadline expires."""

    if state.phase is not Phase.DAY_DISCUSSION:
        raise ValueError(f"当前阶段没有公开发言：{state.phase.value}")
    day_result = _day_result_or_error(state)
    if day_result.speech_deadline is None:
        raise ValueError("当前发言没有可校验的截止时间")
    if now < day_result.speech_deadline:
        raise ValueError("公开发言尚未超时")
    if day_result.next_speaker_index >= len(day_result.speech_order):
        raise ValueError("当前没有等待中的发言者")

    actor_id = day_result.speech_order[day_result.next_speaker_index]
    actor = get_player(state, actor_id)
    if not actor.is_alive:
        raise ValueError("当前发言者不是存活玩家")

    append_event(
        state,
        EventType.PUBLIC_SPEECH_TIMEOUT,
        actor_id=actor_id,
        visibility=Visibility.PUBLIC,
        data={"deadline": day_result.speech_deadline},
    )
    day_result.next_speaker_index += 1
    _arm_public_speech_timer(state, now)
    return state


def self_destruct(
    state: GameState,
    actor_id: str,
    now: float,
) -> GameState:
    """Make a living wolf self-destruct and open or use the 10-second window."""

    actor = get_player(state, actor_id)
    if actor.role is not Role.WEREWOLF:
        raise ValueError("只有狼人可以自爆")
    if not actor.is_alive:
        raise ValueError("死亡狼人不能自爆")
    if state.phase not in {Phase.DAY_DISCUSSION, Phase.SELF_DESTRUCT}:
        raise ValueError(f"当前阶段不能自爆：{state.phase.value}")

    day_result = _day_result_or_error(state)
    if state.phase is Phase.SELF_DESTRUCT:
        if (
            day_result.self_destruct_deadline is None
            or now >= day_result.self_destruct_deadline
        ):
            raise ValueError("自爆窗口已经关闭")
    else:
        state.phase = Phase.SELF_DESTRUCT
        day_result.self_destruct_deadline = now + 10.0

    actor.is_alive = False
    day_result.self_destruct_ids.append(actor.player_id)
    day_result.death_causes[actor.player_id] = ["self_destruct"]
    append_event(
        state,
        EventType.SELF_DESTRUCTED,
        actor_id=actor.player_id,
        visibility=Visibility.PUBLIC,
        data={"revealed_role": Role.WEREWOLF.value, "has_last_words": False},
    )

    winner = check_winner(state)
    if winner is None:
        return state

    day_result.resolved = True
    state.phase = Phase.END
    append_event(
        state,
        EventType.WINNER_DECIDED,
        visibility=Visibility.PUBLIC,
        data={"winner": winner.value, "reason": "self_destruct"},
    )
    return state


def close_self_destruct_window(
    state: GameState,
    now: float | None = None,
) -> GameState:
    """Close the self-destruct window and continue to the next night."""

    if state.phase is not Phase.SELF_DESTRUCT:
        return state
    day_result = _day_result_or_error(state)
    if day_result.self_destruct_deadline is None:
        raise ValueError("自爆窗口尚未建立")
    if now is not None and now < day_result.self_destruct_deadline:
        raise ValueError("自爆窗口尚未结束")
    return _finish_day(state, "self_destruct_window_closed")


def submit_vote(
    state: GameState,
    actor_id: str,
    target_id: str | None,
) -> GameState:
    """Record or replace a living player's current vote."""

    actor = get_player(state, actor_id)
    if not actor.is_alive:
        raise ValueError("死亡玩家不能投票")
    if state.phase is not Phase.VOTE:
        raise ValueError(f"当前阶段不能投票：{state.phase.value}")
    if target_id is not None:
        target = get_player(state, target_id)
        if not target.is_alive:
            raise ValueError("投票目标必须存活")

    day_result = _day_result_or_error(state)
    if day_result.votes_closed:
        raise ValueError("投票已经截止，不能继续改票")
    day_result.votes[actor.player_id] = target_id
    append_event(
        state,
        EventType.VOTE_CAST,
        actor_id=actor.player_id,
        target_id=target_id,
        visibility=Visibility.GOD,
        data={"abstain": target_id is None},
    )
    return state


def close_vote(state: GameState) -> GameState:
    """Close the ballot and lock every player's final vote."""

    if state.phase is not Phase.VOTE:
        raise ValueError(f"当前阶段不能截止投票：{state.phase.value}")
    day_result = _day_result_or_error(state)
    if day_result.votes_closed:
        raise ValueError("投票已经截止")

    day_result.votes_closed = True
    append_event(
        state,
        EventType.VOTE_CLOSED,
        visibility=Visibility.PUBLIC,
        data={"submitted_votes": len(day_result.votes)},
    )
    return state


def resolve_vote(state: GameState) -> GameState:
    """Resolve one vote without a tie-break round."""

    if state.phase is not Phase.VOTE:
        raise ValueError(f"当前阶段不能结算投票：{state.phase.value}")
    day_result = _day_result_or_error(state)
    if not day_result.votes_closed:
        raise ValueError("投票尚未截止")
    if day_result.vote_resolved:
        raise ValueError("本日投票已经结算")

    living_player_ids = _living_speech_order(state)
    final_votes = {
        player_id: day_result.votes.get(player_id)
        for player_id in living_player_ids
    }
    counts = Counter(
        target_id for target_id in final_votes.values() if target_id is not None
    )
    highest = max(counts.values(), default=0)
    leaders = (
        [player_id for player_id, count in counts.items() if count == highest]
        if highest
        else []
    )
    banished_id = leaders[0] if len(leaders) == 1 else None
    result_reason = (
        "unique_highest"
        if banished_id is not None
        else ("tie" if len(leaders) > 1 else "all_abstain")
    )
    day_result.votes = final_votes
    day_result.vote_resolved = True
    append_event(
        state,
        EventType.VOTE_RESULT,
        visibility=Visibility.PUBLIC,
        data={
            "votes": dict(final_votes),
            "tally": dict(counts),
            "banished_id": banished_id,
            "reason": result_reason,
        },
    )

    if not counts:
        return _finish_day(state, "vote_no_elimination")

    if len(leaders) != 1:
        return _finish_day(state, "vote_tie")

    banished = get_player(state, leaders[0])
    banished.is_alive = False
    day_result.banished_id = banished.player_id
    day_result.banishment_pending = True
    day_result.death_causes[banished.player_id] = ["banished"]
    append_event(
        state,
        EventType.PLAYER_DIED,
        target_id=banished.player_id,
        visibility=Visibility.PUBLIC,
        data={"causes": ["banished"]},
    )

    return state


def begin_banishment_last_words(state: GameState) -> GameState:
    """Open last words for the player banished by the resolved vote."""

    if state.phase is not Phase.VOTE:
        raise ValueError(f"当前阶段不能开始放逐遗言：{state.phase.value}")
    day_result = _day_result_or_error(state)
    if not day_result.vote_resolved:
        raise ValueError("投票尚未结算")
    if not day_result.banishment_pending or day_result.banished_id is None:
        raise ValueError("当前没有等待遗言的被放逐玩家")

    banished = get_player(state, day_result.banished_id)
    if banished.role is Role.HUNTER:
        day_result.day_hunter_can_shoot = True
        day_result.after_last_words_phase = Phase.DAY_HUNTER_SHOT
    else:
        day_result.after_last_words_phase = None
    day_result.last_words_queue = [banished.player_id]
    day_result.banishment_pending = False
    state.phase = Phase.DAY_LAST_WORDS
    append_event(
        state,
        EventType.BANISHMENT_LAST_WORDS_STARTED,
        actor_id=banished.player_id,
        visibility=Visibility.PUBLIC,
    )
    return state


def submit_day_hunter_shot(
    state: GameState,
    actor_id: str,
    target_id: str | None,
) -> GameState:
    """Resolve the banished hunter's optional daytime shot."""

    actor = get_player(state, actor_id)
    if actor.role is not Role.HUNTER:
        raise ValueError("只有猎人可以提交猎人开枪")
    if state.phase is not Phase.DAY_HUNTER_SHOT:
        raise ValueError(f"当前阶段不能进行白天猎人开枪：{state.phase.value}")
    day_result = _day_result_or_error(state)
    if not day_result.day_hunter_can_shoot:
        raise ValueError("当前猎人不具备白天开枪资格")

    if target_id is not None:
        target = get_player(state, target_id)
        if not target.is_alive:
            raise ValueError("猎人开枪目标必须存活")

    day_result.day_hunter_can_shoot = False
    day_result.day_hunter_target_id = target_id
    append_event(
        state,
        EventType.HUNTER_SHOT,
        actor_id=actor.player_id,
        target_id=target_id,
        visibility=(
            Visibility.PUBLIC if target_id is not None else Visibility.GOD
        ),
        data={"night": False},
    )

    if target_id is None:
        return _finish_day(state, "day_hunter_no_shot")

    target = get_player(state, target_id)
    target.is_alive = False
    day_result.death_causes[target_id] = ["hunter_shot"]
    append_event(
        state,
        EventType.PLAYER_DIED,
        target_id=target_id,
        visibility=Visibility.PUBLIC,
        data={"causes": ["hunter_shot"]},
    )
    day_result.last_words_queue = [target_id]
    day_result.after_last_words_phase = None
    state.phase = Phase.DAY_LAST_WORDS
    return state


def get_player(state: GameState, identifier: str) -> Player:
    """Find a player by player_id or unique nickname."""

    for player in state.players:
        if player.player_id == identifier or player.name == identifier:
            return player
    raise KeyError(f"找不到玩家：{identifier}")


def start_night(
    state: GameState,
    captain_id: str | None = None,
) -> GameState:
    """Advance the game to the next night.

    The full night-action sequence is intentionally outside this milestone.
    This function only changes the day, phase, and empty night-result object.
    """

    allowed_previous_phases = {
        Phase.INIT,
        Phase.VOTE,
        Phase.SELF_DESTRUCT,
        Phase.DAY_LAST_WORDS,
        Phase.DAY_HUNTER_SHOT,
    }
    if state.phase not in allowed_previous_phases:
        raise ValueError(f"当前阶段不能开始夜晚：{state.phase.value}")

    current_captain = (
        get_player(state, state.wolf_captain_id)
        if state.wolf_captain_id is not None
        else None
    )
    needs_captain = current_captain is None or not current_captain.is_alive
    new_captain: Player | None = None
    selection_method: str | None = None
    if needs_captain:
        new_captain, selection_method = _choose_wolf_captain(
            state,
            captain_id,
            state.day + 1,
        )
    elif captain_id is not None and captain_id != current_captain.player_id:
        raise ValueError("存活狼队长已经存在，不能重复选择")

    state.day += 1
    state.phase = Phase.NIGHT_WOLF_DISCUSSION_R1
    state.night_result = NightResult()
    state.day_result = None
    if new_captain is not None:
        state.wolf_captain_id = new_captain.player_id
        append_event(
            state,
            EventType.WOLF_CAPTAIN_ELECTED,
            target_id=new_captain.player_id,
            visibility=Visibility.WOLVES,
            data={
                "captain_id": new_captain.player_id,
                "day": state.day,
                "selection": selection_method,
            },
        )
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
        if (
            event.event_type is EventType.ROLE_ASSIGNED
            and event.target_id == player.player_id
        ):
            visible_events.append(event)
            continue
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
