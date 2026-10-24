"""Minimal FastAPI entry point for WolfArena."""

from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, status

from .rooms import (
    DuplicateNicknameError,
    InMemoryRoomRepository,
    InvalidPlayerTokenError,
    RoomFullError,
    RoomNotFoundError,
)
from .schemas import (
    CreateRoomRequest,
    CreatedRoomResponse,
    HealthResponse,
    JoinedRoomResponse,
    JoinRoomRequest,
    RoomSnapshot,
)


APP_VERSION = "0.1.0"


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def create_app(repository: InMemoryRoomRepository | None = None) -> FastAPI:
    application = FastAPI(
        title="WolfArena API",
        version=APP_VERSION,
        description="WolfArena 九人局最小 Web 入口",
    )
    application.state.rooms = repository or InMemoryRoomRepository()

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="wolfarena-api",
            version=APP_VERSION,
        )

    @application.post(
        "/api/rooms",
        response_model=CreatedRoomResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_room(payload: CreateRoomRequest) -> CreatedRoomResponse:
        try:
            return application.state.rooms.create_room(
                seed=payload.seed,
                human_count=payload.human_count,
                max_humans=payload.max_humans,
                nickname=payload.nickname,
            )
        except DuplicateNicknameError as error:
            raise _error(409, "DUPLICATE_NICKNAME", str(error)) from error
        except ValueError as error:
            raise _error(422, "INVALID_ROOM_CONFIG", str(error)) from error

    @application.post(
        "/api/rooms/{room_id}/join",
        response_model=JoinedRoomResponse,
    )
    def join_room(room_id: str, payload: JoinRoomRequest) -> JoinedRoomResponse:
        try:
            return application.state.rooms.join_room(room_id, payload.nickname)
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except RoomFullError as error:
            raise _error(409, "ROOM_FULL", str(error)) from error
        except DuplicateNicknameError as error:
            raise _error(409, "DUPLICATE_NICKNAME", str(error)) from error

    @application.get(
        "/api/rooms/{room_id}",
        response_model=RoomSnapshot,
    )
    def get_room(
        room_id: str,
        player_token: str | None = Header(default=None, alias="X-Player-Token"),
    ) -> RoomSnapshot:
        try:
            return application.state.rooms.get_snapshot(room_id, player_token)
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except InvalidPlayerTokenError as error:
            raise _error(
                status.HTTP_401_UNAUTHORIZED,
                "INVALID_PLAYER_TOKEN",
                str(error),
            ) from error

    return application


app = create_app()
