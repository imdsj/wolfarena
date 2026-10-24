"""In-memory room repository for the first Web entry milestone."""

from __future__ import annotations

from dataclasses import dataclass, field
from secrets import token_urlsafe
from threading import RLock

from .game_engine import GameState, Player, create_game, get_player, get_visible_events
from .schemas import (
    CreatedRoomResponse,
    JoinedRoomResponse,
    PublicEvent,
    PublicPlayer,
    RoomSnapshot,
    ViewerPlayer,
)


class RoomNotFoundError(LookupError):
    """Raised when a room does not exist."""


class InvalidPlayerTokenError(PermissionError):
    """Raised when a player credential is missing or invalid."""


class RoomFullError(RuntimeError):
    """Raised when another human cannot join the room."""


class DuplicateNicknameError(ValueError):
    """Raised when a nickname is already used in the game."""


@dataclass(slots=True)
class Room:
    """One game and the credentials used to access it."""

    room_id: str
    state: GameState
    max_humans: int
    reserved_human_count: int
    claimed_player_ids: set[str] = field(default_factory=set)
    tokens_by_player: dict[str, str] = field(default_factory=dict)
    player_by_token: dict[str, str] = field(default_factory=dict)

    @property
    def human_count(self) -> int:
        return len(self.claimed_player_ids)

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
    """Thread-safe room store used by local development and tests."""

    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._lock = RLock()

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

        with self._lock:
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
            )
            creator = get_player(state, "p1")
            token = room.claim_player(creator.player_id)
            self._rooms[room_id] = room
            return CreatedRoomResponse(
                room_id=room_id,
                player_token=token,
                room=self.snapshot(room, token),
            )

    def join_room(self, room_id: str, nickname: str) -> JoinedRoomResponse:
        with self._lock:
            room = self._get_room(room_id)
            player = room.choose_join_seat()
            room.rename_player(player, nickname)
            token = room.claim_player(player.player_id)
            return JoinedRoomResponse(
                player_token=token,
                room=self.snapshot(room, token),
            )

    def get_snapshot(self, room_id: str, token: str | None) -> RoomSnapshot:
        with self._lock:
            room = self._get_room(room_id)
            return self.snapshot(room, token)

    def snapshot(self, room: Room, token: str | None) -> RoomSnapshot:
        viewer = room.player_for_token(token)
        visible_events = get_visible_events(room.state, viewer)
        return RoomSnapshot(
            room_id=room.room_id,
            phase=room.state.phase.value,
            day=room.state.day,
            human_count=room.human_count,
            max_humans=room.max_humans,
            viewer=ViewerPlayer(
                player_id=viewer.player_id,
                seat=viewer.seat,
                name=viewer.name,
                role=viewer.role.value,
                is_alive=viewer.is_alive,
            ),
            players=[
                PublicPlayer(
                    player_id=player.player_id,
                    seat=player.seat,
                    name=player.name,
                    is_human=player.player_id in room.claimed_player_ids,
                    is_alive=player.is_alive,
                )
                for player in sorted(room.state.players, key=lambda item: item.seat)
            ],
            visible_events=[
                PublicEvent(
                    event_seq=event.event_seq,
                    event_type=event.event_type.value,
                    day=event.day,
                    phase=event.phase.value,
                    actor_id=event.actor_id,
                    target_id=event.target_id,
                    visibility=event.visibility.value,
                    data=dict(event.data),
                )
                for event in visible_events
            ],
        )

    def _get_room(self, room_id: str) -> Room:
        try:
            return self._rooms[room_id]
        except KeyError as error:
            raise RoomNotFoundError("房间不存在") from error

    def _new_room_id(self) -> str:
        while True:
            room_id = token_urlsafe(6)
            if room_id not in self._rooms:
                return room_id
