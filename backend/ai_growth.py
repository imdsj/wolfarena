"""Auditable AI growth records and the non-LLM L0 policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from random import Random
from typing import Final, Sequence

from .game_engine import (
    EventType,
    GameState,
    Phase,
    Role,
    get_visible_events,
)


class GrowthStage(str, Enum):
    """Stable growth stages shared by the backend and frontend."""

    L0_NOVICE = "L0_NOVICE"
    L1_RULE = "L1_RULE"
    L2_STRATEGY = "L2_STRATEGY"
    L3_ADVERSARIAL = "L3_ADVERSARIAL"


GROWTH_STAGE_ORDER: Final[tuple[GrowthStage, ...]] = (
    GrowthStage.L0_NOVICE,
    GrowthStage.L1_RULE,
    GrowthStage.L2_STRATEGY,
    GrowthStage.L3_ADVERSARIAL,
)


def speech_content(state: GameState, actor, view) -> str | None:
    """Role-aware, deterministic speech that only uses public information.

    It never reads another player's hidden role. It uses the actor's own role,
    seat, the public list of living players, the day/phase and the current event
    count, so swapping every other player's role leaves the text unchanged.
    """

    if not view.requires_content:
        return None
    rng = Random(
        f"{state.seed}:speech:{len(state.events)}:"
        f"{actor.player_id}:{view.action}"
    )
    seat = actor.seat
    others = [
        player
        for player in state.players
        if player.is_alive and player.player_id != actor.player_id
    ]
    pick = rng.choice(others) if others else None

    if view.action == "wolf_speech":
        if pick is not None:
            return rng.choice(
                [
                    f"狼队频道 {seat} 号：刀 {pick.seat} 号我同意；白天我去悍跳预言家，"
                    "另一个队友跟票，剩下的别抢话，先看我报查验。",
                    f"狼队频道 {seat} 号：刀口定 {pick.seat} 号；白天我踩他带节奏，"
                    "队友一个跟票一个深水，别一起冲。",
                    f"狼队频道 {seat} 号：{pick.seat} 号威胁最大，今晚处理他；"
                    "如果女巫救人，白天我装作不信预言家，队友补刀跟票。",
                ]
            )
        return (
            f"狼队频道 {seat} 号：刀口按队长定的走；白天我去悍跳预言家，"
            "队友一个跟票一个深水，别分票。"
        )

    if view.action == "last_words":
        return rng.choice(
            [
                f"我是 {seat} 号，遗言：注意票型反常的人，好人别分票。",
                f"我是 {seat} 号，遗言：我票投给最可疑的人，别跟风。",
                f"我是 {seat} 号，遗言：好人看清投票，别被带节奏。",
            ]
        )

    last_speaker_seat: int | None = None
    for event in reversed(get_visible_events(state, actor)):
        if (
            event.event_type is EventType.PUBLIC_SPEECH
            and event.actor_id
            and event.actor_id != actor.player_id
        ):
            speaker = next(
                (
                    player
                    for player in state.players
                    if player.player_id == event.actor_id
                ),
                None,
            )
            last_speaker_seat = speaker.seat if speaker else None
            break

    def with_reference(text: str) -> str:
        if last_speaker_seat is None:
            return text
        return f"回应 {last_speaker_seat} 号：{text}"

    role = actor.role
    if role is Role.SEER:
        # Announcing "I am the seer" every day is suicidal: the wolf kill
        # heuristic hunts public god claims. Only claim once there is a wolf
        # result worth acting on.
        reports: list[tuple[int, str]] = []
        for event in get_visible_events(state, actor):
            if event.event_type is not EventType.SEER_CHECKED:
                continue
            target = next(
                (
                    player
                    for player in state.players
                    if player.player_id == event.target_id
                ),
                None,
            )
            if target is not None:
                reports.append((target.seat, str(event.data.get("result"))))
        wolf_seats = [seat for seat, result in reports if result == "wolf"]
        if wolf_seats:
            return f"我是预言家，{wolf_seats[-1]} 号是狼，今天票 {wolf_seats[-1]} 号。"
        if reports:
            # Day one info is too valuable to sit on: claim and report the
            # latest check so the good side actually has something to act on.
            seat_checked, result = reports[-1]
            verdict = "狼人" if result == "wolf" else "好人"
            return (
                f"我是预言家，昨晚查验 {seat_checked} 号是{verdict}，"
                "好人跟我的票，别让狼人带节奏。"
            )
        return f"我 {seat} 号先听一轮。"

    # A good player who spots an impossible claim should name it. Without
    # this branch the template only talks about generic suspicion, so the
    # clearest information on the table never reaches the vote.
    try:
        from .logic_audit import strongest_finding

        finding = strongest_finding(state, actor, exclude_speaker=seat)
    except Exception:
        finding = None
    if finding is not None and role is not Role.WEREWOLF:
        return (
            f"我 {seat} 号先抓一个逻辑漏洞：{finding.detail}，"
            f"今天先票 {finding.speaker_seat} 号。"
        )

    if role is Role.WITCH:
        return rng.choice(
            [
                "我会谨慎用药，在没把握时不公开行动，避免暴露身份。",
                "用药我会留到关键时刻，没把握之前不公开说。",
                "我会根据今晚的刀口决定用药，先不暴露。",
            ]
        )

    if role is Role.HUNTER:
        return rng.choice(
            [
                "我是猎人，谁票我我带走谁，好人别乱投。",
                "我是猎人，别急着票我，不然我开枪带走一个。",
                "我是猎人，我的枪还在，投票前想清楚。",
            ]
        )

    if role is Role.WEREWOLF:
        if pick is not None:
            return with_reference(
                rng.choice(
                    [
                        f"我 {seat} 号觉得 {pick.seat} 号发言有点虚，大家留意。",
                        f"我 {seat} 号先听一轮，{pick.seat} 号我再观察。",
                        f"我 {seat} 号目前比较怀疑 {pick.seat} 号，理由先听后置位。",
                    ]
                )
            )
        return f"我 {seat} 号先听一轮再表态。"

    if pick is not None:
        return with_reference(
            rng.choice(
                [
                    f"我是村民，我怀疑 {pick.seat} 号，他的投票和发言对不上。",
                    f"我是村民，我看 {pick.seat} 号有点问题，先记着。",
                    f"我是村民，目前最怀疑 {pick.seat} 号，等下看他怎么解释。",
                ]
            )
        )
    return f"我 {seat} 号目前没有明确怀疑对象。"


@dataclass(slots=True)
class DecisionRecord:
    """One auditable action choice made by a player or agent."""

    game_id: str
    seed: int
    day: int
    phase: Phase
    player_id: str
    role: Role
    legal_actions: tuple[str, ...]
    chosen_action: str
    strategy_id: str
    confidence: float
    outcome: str | None = None
    reflection: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.game_id, str) or not self.game_id.strip():
            raise ValueError("game_id 必须是非空字符串")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数")
        if isinstance(self.day, bool) or not isinstance(self.day, int):
            raise ValueError("day 必须是整数")
        if self.day < 0:
            raise ValueError("day 不能小于 0")
        if not isinstance(self.phase, Phase):
            raise ValueError("phase 必须是 Phase")
        if not isinstance(self.player_id, str) or not self.player_id.strip():
            raise ValueError("player_id 必须是非空字符串")
        if not isinstance(self.role, Role):
            raise ValueError("role 必须是 Role")

        legal_actions = tuple(self.legal_actions)
        if not legal_actions:
            raise ValueError("legal_actions 不能为空")
        if any(
            not isinstance(action, str) or not action.strip()
            for action in legal_actions
        ):
            raise ValueError("每个合法动作必须是非空字符串")
        if len(set(legal_actions)) != len(legal_actions):
            raise ValueError("legal_actions 不能包含重复动作")
        if (
            not isinstance(self.chosen_action, str)
            or self.chosen_action not in legal_actions
        ):
            raise ValueError("chosen_action 必须来自 legal_actions")
        if not isinstance(self.strategy_id, str) or not self.strategy_id.strip():
            raise ValueError("strategy_id 必须是非空字符串")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0 <= self.confidence <= 1
        ):
            raise ValueError("confidence 必须在 0 到 1 之间")

        self.legal_actions = legal_actions
        self.confidence = float(self.confidence)
        self.outcome = self.outcome.strip() if self.outcome else None
        self.reflection = self.reflection.strip() if self.reflection else None


@dataclass(slots=True)
class StrategyRecord:
    """A strategy entry whose metrics remain unknown until real samples exist."""

    strategy_id: str
    role: Role
    phase: Phase
    trigger: str
    action: str
    source: str
    samples: int = 0
    win_rate: float | None = None
    interval: tuple[float, float] | None = None
    version: str = "v0.1"
    status: str = "untested"

    def __post_init__(self) -> None:
        for field_name in (
            "strategy_id",
            "trigger",
            "action",
            "source",
            "version",
            "status",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} 必须是非空字符串")
        if not isinstance(self.role, Role):
            raise ValueError("role 必须是 Role")
        if not isinstance(self.phase, Phase):
            raise ValueError("phase 必须是 Phase")
        if (
            isinstance(self.samples, bool)
            or not isinstance(self.samples, int)
            or self.samples < 0
        ):
            raise ValueError("samples 必须是大于等于 0 的整数")

        if self.win_rate is not None:
            if (
                isinstance(self.win_rate, bool)
                or not isinstance(self.win_rate, (int, float))
                or not 0 <= self.win_rate <= 1
            ):
                raise ValueError("win_rate 必须在 0 到 1 之间")
            self.win_rate = float(self.win_rate)
            if self.samples == 0:
                raise ValueError("没有真实样本时不能填写 win_rate")

        if self.interval is not None:
            if (
                not isinstance(self.interval, tuple)
                or len(self.interval) != 2
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not 0 <= value <= 1
                    for value in self.interval
                )
                or self.interval[0] > self.interval[1]
            ):
                raise ValueError("interval 必须是 0 到 1 之间的有序二元组")
            self.interval = (float(self.interval[0]), float(self.interval[1]))
            if self.win_rate is None or self.samples == 0:
                raise ValueError("没有真实胜率和样本时不能填写 interval")


@dataclass(slots=True)
class L0Policy:
    """A deterministic random policy that only selects server-approved actions."""

    seed: int
    strategy_id: str = "l0.random.v1"
    stage: GrowthStage = GrowthStage.L0_NOVICE
    _rng: Random = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数")
        if self.stage is not GrowthStage.L0_NOVICE:
            raise ValueError("L0Policy 只能使用 L0_NOVICE 阶段")
        self._rng = Random(self.seed)

    def choose_action(self, legal_actions: Sequence[str]) -> str:
        """Choose exactly one action from a non-empty, unique action list."""

        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("没有合法动作可供选择")
        if any(
            not isinstance(action, str) or not action.strip()
            for action in actions
        ):
            raise ValueError("每个合法动作必须是非空字符串")
        if len(set(actions)) != len(actions):
            raise ValueError("合法动作不能重复")

        chosen = self._rng.choice(actions)
        if chosen not in actions:
            raise RuntimeError("L0 选择了不在 legal_actions 中的动作")
        return chosen

    def make_decision(
        self,
        *,
        game_id: str,
        day: int,
        phase: Phase,
        player_id: str,
        role: Role,
        legal_actions: Sequence[str],
    ) -> DecisionRecord:
        """Choose an action and return an auditable decision record."""

        actions = tuple(legal_actions)
        chosen = self.choose_action(actions)
        return DecisionRecord(
            game_id=game_id,
            seed=self.seed,
            day=day,
            phase=phase,
            player_id=player_id,
            role=role,
            legal_actions=actions,
            chosen_action=chosen,
            strategy_id=self.strategy_id,
            confidence=0.0,
        )


@dataclass(slots=True)
class L1RulePolicy:
    """A deterministic rule policy that uses only legal actions and views."""

    seed: int
    strategy_id: str = "l1.rule.v1"
    stage: GrowthStage = GrowthStage.L1_RULE

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed 必须是整数")
        if self.stage is not GrowthStage.L1_RULE:
            raise ValueError("L1RulePolicy 只能使用 L1_RULE 阶段")

    def choose_action(self, legal_actions: Sequence[str]) -> str:
        actions = tuple(legal_actions)
        if not actions:
            raise ValueError("没有合法动作可供选择")
        if len(set(actions)) != len(actions):
            raise ValueError("合法动作不能重复")
        priority = (
            "wolf_speech",
            "seer_check",
            "witch_action",
            "night_hunter_shot",
            "day_hunter_shot",
            "speech",
            "last_words",
            "vote",
            "wolf_kill",
            "start_night",
            "resolve_night",
            "begin_day",
            "close_vote",
            "resolve_vote",
            "begin_banishment_last_words",
            "close_self_destruct_window",
            "self_destruct",
        )
        for action in priority:
            if action in actions:
                return action
        return actions[0]

    def choose_choice(
        self,
        state: GameState,
        actor,
        view,
    ) -> str | None:
        if not view.choices:
            return None
        if view.action == "witch_action":
            night_result = state.night_result
            if (
                "antidote" in view.choices
                and state.antidote_available
                and night_result is not None
                and night_result.wolf_target_id in view.target_ids
            ):
                return "antidote"
            if "poison" in view.choices and state.poison_available:
                if self._witch_poison_target(state, actor, view) is not None:
                    return "poison"
            if "none" in view.choices:
                return "none"
        return view.choices[0]

    def choose_target(
        self,
        state: GameState,
        actor,
        view,
        *,
        choice: str | None,
    ) -> str | None:
        if not view.target_ids:
            return None
        if view.action == "witch_action":
            if choice == "poison":
                return self._witch_poison_target(state, actor, view)
            if choice == "antidote":
                night_result = state.night_result
                target = (
                    night_result.wolf_target_id
                    if night_result is not None
                    else None
                )
                return target if target in view.target_ids else None
            return None
        if view.action == "wolf_kill":
            return self._wolf_kill_target(state, actor, view)
        if view.action == "seer_check":
            return self._seer_check_target(state, actor, view)
        if view.action == "vote":
            return self._vote_target(state, actor, view)
        if view.action in {"night_hunter_shot", "day_hunter_shot"}:
            return self._hunter_target(state, actor, view)
        return view.target_ids[0]

    def _hunter_target(self, state, actor, view) -> str | None:
        """Only shoot with a real read; holding the gun beats a random kill."""

        from .public_signals import build_signals

        try:
            signals = build_signals(state, actor)
        except Exception:
            signals = None
        if signals is not None:
            for seat in reversed(signals.reported_wolves()):
                for player in state.players:
                    if (
                        player.seat == seat
                        and player.player_id in view.target_ids
                        and player.player_id != actor.player_id
                    ):
                        return player.player_id
            seat = signals.top_accused(exclude=actor.seat, minimum=2)
            if seat is not None:
                for player in state.players:
                    if (
                        player.seat == seat
                        and player.player_id in view.target_ids
                        and player.player_id != actor.player_id
                    ):
                        return player.player_id
        return None

    def _witch_poison_target(self, state, actor, view) -> str | None:
        """Poison only a seat a self-claimed seer has reported as a wolf."""

        from .public_signals import build_signals

        try:
            signals = build_signals(state, actor)
        except Exception:
            return None
        for seat in reversed(signals.reported_wolves()):
            for player in state.players:
                if (
                    player.seat == seat
                    and player.player_id in view.target_ids
                    and player.player_id != actor.player_id
                ):
                    return player.player_id
        return None

    def _vote_target(self, state, actor, view) -> str:
        """Follow public suspicion; never collapse onto seat 1 by default."""

        from .public_signals import build_signals

        # A seer's own gold-water is the one player they know is good. They
        # must never vote it out, even if the table is piling on.
        trusted_good: set[str] = set()
        if actor.role is Role.SEER:
            trusted_good = {
                event.target_id
                for event in get_visible_events(state, actor)
                if event.event_type is EventType.SEER_CHECKED
                and event.data.get("result") == "good"
                and event.target_id
            }

        try:
            signals = build_signals(state, actor)
        except Exception:
            signals = None
        if signals is not None:
            # Follow a public seer report ("X号是狼") first, otherwise the
            # seer's decision to claim on day one cannot pay off.
            for seat in reversed(signals.reported_wolves()):
                for player in state.players:
                    if (
                        player.seat == seat
                        and player.player_id in view.target_ids
                        and player.player_id != actor.player_id
                        and player.player_id not in trusted_good
                    ):
                        return player.player_id
            # A spoken contradiction is stronger than a pile-on accusation:
            # the table can shout at anyone, but only a wolf can know an
            # unspoken player's role.
            try:
                from .logic_audit import top_suspect

                audit_seat = top_suspect(state, actor, exclude=actor.seat)
            except Exception:
                audit_seat = None
            if audit_seat is not None:
                for player in state.players:
                    if (
                        player.seat == audit_seat
                        and player.player_id in view.target_ids
                        and player.player_id not in trusted_good
                    ):
                        return player.player_id
            seat = signals.top_accused(exclude=actor.seat)
            if seat is not None:
                for player in state.players:
                    if (
                        player.seat == seat
                        and player.player_id in view.target_ids
                        and player.player_id not in trusted_good
                    ):
                        return player.player_id
        rng = Random(f"{self.seed}:vote:{state.day}:{actor.player_id}")
        choices = [
            player_id
            for player_id in view.target_ids
            if player_id != actor.player_id and player_id not in trusted_good
        ]
        fallback = [
            player_id
            for player_id in view.target_ids
            if player_id not in trusted_good
        ]
        return rng.choice(choices or fallback or list(view.target_ids))

    def _wolf_kill_target(self, state, actor, view) -> str:
        """Kill a god claim first, else a threat; never always seat 1."""

        from .public_signals import build_signals

        def is_wolf(player_id: str) -> bool:
            return any(
                player.player_id == player_id
                and player.role is Role.WEREWOLF
                for player in state.players
            )

        prey = [
            player_id
            for player_id in view.target_ids
            if not is_wolf(player_id)
        ] or list(view.target_ids)

        agreed = self._wolf_agreed_target(state, actor, prey)
        if agreed is not None:
            return agreed

        claimed = self._claimed_god_ids(state, actor)
        for player_id in prey:
            if player_id in claimed:
                return player_id

        try:
            signals = build_signals(state, actor)
        except Exception:
            signals = None
        if signals is not None:
            seat = signals.top_accused(exclude=actor.seat)
            if seat is not None:
                for player in state.players:
                    if player.seat == seat and player.player_id in prey:
                        return player.player_id

        rng = Random(f"{self.seed}:kill:{state.day}:{actor.player_id}")
        choices = [player_id for player_id in prey if player_id != actor.player_id]
        return rng.choice(choices or prey)

    def _wolf_agreed_target(self, state, actor, prey: list[str]) -> str | None:
        """Honour the latest kill target the wolf channel actually agreed on."""

        import re

        pattern = re.compile(
            r"(?:刀|杀|带走|做掉|处理|集火)\s*(\d{1,2})\s*号?"
            r"|刀口\s*(?:定|在|是|为|选)?\s*(\d{1,2})\s*号?"
            r"|(\d{1,2})\s*号\s*(?:是|作为|当)\s*刀口"
        )
        for event in reversed(get_visible_events(state, actor)):
            if event.event_type is not EventType.WOLF_SPEECH:
                continue
            content = event.data.get("content")
            if not isinstance(content, str):
                continue
            for match in reversed(list(pattern.finditer(content))):
                prefix = content[max(0, match.start() - 2) : match.start()]
                if "不" in prefix or "别" in prefix:
                    continue
                seat = int(
                    match.group(1) or match.group(2) or match.group(3)
                )
                for player in state.players:
                    if player.seat == seat and player.player_id in prey:
                        return player.player_id
        return None

    def _seer_check_target(self, state, actor, view) -> str:
        """Check a suspicious, not-yet-checked player, never just seat 1."""

        from .public_signals import build_signals

        checked = {
            event.target_id
            for event in get_visible_events(state, actor)
            if event.event_type is EventType.SEER_CHECKED
        }
        candidates = [
            player_id
            for player_id in view.target_ids
            if player_id not in checked
        ] or list(view.target_ids)

        try:
            signals = build_signals(state, actor)
        except Exception:
            signals = None
        if signals is not None:
            seat = signals.top_accused(exclude=actor.seat)
            if seat is not None:
                for player in state.players:
                    if (
                        player.seat == seat
                        and player.player_id in candidates
                    ):
                        return player.player_id

        rng = Random(f"{self.seed}:check:{state.day}:{actor.player_id}")
        return rng.choice(candidates)

    @staticmethod
    def choose_content(state, actor, view) -> str | None:
        return speech_content(state, actor, view)

    @staticmethod
    def _claimed_god_ids(state: GameState, actor) -> set[str]:
        keywords = ("预言家", "女巫", "猎人")
        claims: set[str] = set()
        for event in get_visible_events(state, actor):
            if event.event_type not in {
                EventType.PUBLIC_SPEECH,
                EventType.LAST_WORDS,
            }:
                continue
            content = event.data.get("content")
            if (
                event.actor_id
                and isinstance(content, str)
                and any(keyword in content for keyword in keywords)
            ):
                claims.add(event.actor_id)
        return claims
