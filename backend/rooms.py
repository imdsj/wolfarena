"""Thread-safe in-memory rooms and viewer-scoped WebSocket state."""

from __future__ import annotations

from dataclasses import dataclass, field
from secrets import compare_digest, token_urlsafe
from threading import RLock
from typing import Literal

from .game_engine import (
    Event,
    EventType,
    GameState,
    Phase,
    Player,
    SPECTATOR_VIEW,
    Visibility,
    append_event,
    create_game,
    get_player,
    get_visible_events,
    start_night as advance_to_night,
)
from .schemas import (
    CreatedRoomResponse,
    JoinedRoomResponse,
    PublicEvent,
    PublicPlayer,
    RoomSnapshot,
    ViewerIdentity,
)


class RoomNotFoundError(LookupError):
    """Raised when a room does not exist."""


class InvalidPlayerTokenError(PermissionError):
    """Raised when a player credential is missing or invalid."""


class InvalidSpectatorPasswordError(PermissionError):
    """Raised when a spectator password is invalid."""


class RoomFullError(RuntimeError):
    """Raised when another human cannot join the room."""


class DuplicateNicknameError(ValueError):
    """Raised when a nickname is already used in the game."""


class JoinClosedError(RuntimeError):
    """Raised when a room no longer accepts new players."""


class RoomPermissionError(PermissionError):
    """Raised when a viewer cannot perform an action."""


class OutOfPhaseError(RuntimeError):
    """Raised when an action is invalid for the current game phase."""


class UnsupportedActionError(ValueError):
    """Raised when the action name is not implemented."""


@dataclass(frozen=True, slots=True)
class ViewerAccess:
    """Authenticated identity used to filter room events."""

    room_id: str
    kind: Literal["player", "spectator"]
    player_id: str | None = None


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """An authenticated viewer and the snapshot visible at login time."""

    room: "Room"
    access: ViewerAccess
    snapshot: RoomSnapshot


@dataclass(frozen=True, slots=True)
class RoomMutation:
    """A committed room change and the event range it produced."""

    room: "Room"
    previous_event_seq: int
    current_event_seq: int


@dataclass(slots=True)
class Room:
    """One game, its credentials, and its serialization lock."""

    room_id: str
    state: GameState
    max_humans: int
    reserved_human_count: int
    spectator_password: str
    host_player_id: str = "p1"
    claimed_player_ids: set[str] = field(default_factory=set)
    tokens_by_player: dict[str, str] = field(default_factory=dict)
    player_by_token: dict[str, str] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock, repr=False)

    @property
    def human_count(self) -> int:
        return len(self.claimed_player_ids)

    @property
    def last_event_seq(self) -> int:
        return self.state.events[-1].event_seq if self.state.events else -1

    def claim_player(self, player_id: str) -> str:
        """Create and remember a credential for one player."""

        token = token_urlsafe(32)
        self.claimed_player_ids.add(player_id)
        self.tokens_by_player[player_id] = token
        self.player_by_token[token] = player_id
        return token

    def player_for_token(self, token: str | None) -> Player:
        if not token:
            raise InvalidPlayerTokenError("缺少玩家凭证")
        player_id = self.player_by_token.get(token)
        if player_id is None:
            raise InvalidPlayerTokenError("玩家凭证无效")
        return get_player(self.state, player_id)

    def choose_join_seat(self) -> Player:
        """Choose a reserved human seat first, then convert an AI seat."""

        if self.human_count >= self.max_humans:
            raise RoomFullError("房间真人已满")

        unclaimed = [
            player
            for player in self.state.players
            if player.player_id not in self.claimed_player_ids
        ]
        reserved = [
            player
            for player in unclaimed
            if player.seat <= self.reserved_human_count
        ]
        return min(reserved or unclaimed, key=lambda player: player.seat)

    def rename_player(self, player: Player, nickname: str) -> None:
        if any(
            other.player_id != player.player_id and other.name == nickname
            for other in self.state.players
        ):
            raise DuplicateNicknameError("昵称已被使用")
        player.name = nickname
        player.is_human = True


class InMemoryRoomRepository:
    """Room store that serializes mutations per room."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._registry_lock = RLock()

    def create_room(
        self,
        *,
        seed: int,
        human_count: int,
        max_humans: int,
        nickname: str,
    ) -> CreatedRoomResponse:
        if human_count > max_humans:
            raise ValueError("human_count 不能大于 max_humans")

        names = [nickname] + [f"玩家{seat}" for seat in range(2, 10)]
        if len(set(names)) != len(names):
            raise DuplicateNicknameError("昵称与默认玩家名称冲突")

        with self._registry_lock:
            room_id = self._new_room_id()
            state = create_game(
                seed=seed,
                human_count=human_count,
                player_names=names,
            )
            room = Room(
                room_id=room_id,
                state=state,
                max_humans=max_humans,
                reserved_human_count=human_count,
                spectator_password=token_urlsafe(12),
            )
            creator = get_player(state, "p1")
            token = room.claim_player(creator.player_id)
            self._rooms[room_id] = room
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=creator.player_id,
            )
            return CreatedRoomResponse(
                room_id=room_id,
                player_token=token,
                spectator_password=room.spectator_password,
                room=self.snapshot_for_access(room, access),
            )

    def join_room(
        self,
        room_id: str,
        nickname: str,
    ) -> tuple[JoinedRoomResponse, RoomMutation]:
        room = self._get_room(room_id)
        with room.lock:
            if room.state.phase is not Phase.INIT:
                raise JoinClosedError("游戏开始后不能加入新玩家")

            previous_event_seq = room.last_event_seq
            player = room.choose_join_seat()
            room.rename_player(player, nickname)
            token = room.claim_player(player.player_id)
            append_event(
                room.state,
                EventType.PLAYER_JOINED,
                target_id=player.player_id,
                visibility=Visibility.PUBLIC,
                data={
                    "seat": player.seat,
                    "name": player.name,
                },
            )
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=player.player_id,
            )
            response = JoinedRoomResponse(
                player_token=token,
                room=self.snapshot_for_access(room, access),
            )
            mutation = RoomMutation(
                room=room,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )
            return response, mutation

    def authenticate_player(
        self,
        room_id: str,
        token: str | None,
    ) -> AuthenticatedSession:
        room = self._get_room(room_id)
        with room.lock:
            player = room.player_for_token(token)
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=player.player_id,
            )
            return AuthenticatedSession(
                room=room,
                access=access,
                snapshot=self.snapshot_for_access(room, access),
            )

    def authenticate_spectator(
        self,
        room_id: str,
        password: str | None,
    ) -> AuthenticatedSession:
        room = self._get_room(room_id)
        with room.lock:
            if (
                not password
                or not compare_digest(password, room.spectator_password)
            ):
                raise InvalidSpectatorPasswordError("观战密码错误")
            access = ViewerAccess(room_id=room_id, kind="spectator")
            return AuthenticatedSession(
                room=room,
                access=access,
                snapshot=self.snapshot_for_access(room, access),
            )

    def get_snapshot(self, room_id: str, token: str | None) -> RoomSnapshot:
        room = self._get_room(room_id)
        with room.lock:
            player = room.player_for_token(token)
            access = ViewerAccess(
                room_id=room_id,
                kind="player",
                player_id=player.player_id,
            )
            return self.snapshot_for_access(room, access)

    def start_night(
        self,
        access: ViewerAccess,
        *,
        captain_id: str | None = None,
    ) -> RoomMutation:
        room = self._get_room(access.room_id)
        with room.lock:
            if access.kind != "player" or access.player_id != room.host_player_id:
                raise RoomPermissionError("只有房主可以开始游戏")
            if room.state.phase is not Phase.INIT:
                raise OutOfPhaseError(
                    f"当前阶段不能开始夜晚：{room.state.phase.value}"
                )

            previous_event_seq = room.last_event_seq
            advance_to_night(room.state, captain_id)
            return RoomMutation(
                room=room,
                previous_event_seq=previous_event_seq,
                current_event_seq=room.last_event_seq,
            )

    def visible_events_since(
        self,
        room: Room,
        access: ViewerAccess,
        after_event_seq: int,
    ) -> tuple[Event, ...]:
        with room.lock:
            viewer = self._event_viewer(room, access)
            return tuple(
                event
                for event in get_visible_events(room.state, viewer)
                if event.event_seq > after_event_seq
            )

    def snapshot_for_access(
        self,
        room: Room,
        access: ViewerAccess,
    ) -> RoomSnapshot:
        with room.lock:
            viewer = self._event_viewer(room, access)
            visible_events = get_visible_events(room.state, viewer)
            if access.kind == "spectator":
                viewer_identity = ViewerIdentity(
                    kind="spectator",
                    player_id=None,
                    seat=None,
                    name="观战者",
                    role=None,
                    is_alive=None,
                    is_host=False,
                )
            else:
                player = self._access_player(room, access)
                viewer_identity = ViewerIdentity(
                    kind="player",
                    player_id=player.player_id,
                    seat=player.seat,
                    name=player.name,
                    role=player.role.value,
                    is_alive=player.is_alive,
                    is_host=player.player_id == room.host_player_id,
                )

            return RoomSnapshot(
                room_id=room.room_id,
                phase=room.state.phase.value,
                day=room.state.day,
                human_count=room.human_count,
                max_humans=room.max_humans,
                viewer=viewer_identity,
                players=[
                    PublicPlayer(
                        player_id=player.player_id,
                        seat=player.seat,
                        name=player.name,
                        is_human=player.player_id in room.claimed_player_ids,
                        is_alive=player.is_alive,
                    )
                    for player in sorted(
                        room.state.players,
                        key=lambda item: item.seat,
                    )
                ],
                visible_events=[
                    self.serialize_event(event)
                    for event in visible_events
                ],
            )

    @staticmethod
    def serialize_event(event: Event) -> PublicEvent:
        return PublicEvent(
            event_seq=event.event_seq,
            event_type=event.event_type.value,
            day=event.day,
            phase=event.phase.value,
            actor_id=event.actor_id,
            target_id=event.target_id,
            visibility=event.visibility.value,
            data=dict(event.data),
        )

    def _event_viewer(self, room: Room, access: ViewerAccess) -> Player | str:
        if access.kind == "spectator":
            return SPECTATOR_VIEW
        return self._access_player(room, access)

    @staticmethod
    def _access_player(room: Room, access: ViewerAccess) -> Player:
        if access.player_id is None:
            raise InvalidPlayerTokenError("缺少玩家身份")
        try:
            return get_player(room.state, access.player_id)
        except KeyError as error:
            raise InvalidPlayerTokenError("玩家不属于当前房间") from error

    def _get_room(self, room_id: str) -> Room:
        with self._registry_lock:
            try:
                return self._rooms[room_id]
            except KeyError as error:
                raise RoomNotFoundError("房间不存在") from error

    def _new_room_id(self) -> str:
        while True:
            room_id = token_urlsafe(6)
            if room_id not in self._rooms:
                return room_id
