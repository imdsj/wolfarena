"""Minimal FastAPI entry point for WolfArena."""

from __future__ import annotations

import asyncio
from json import JSONDecodeError
from typing import Any

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from .realtime import RealtimeHub
from .rooms import (
    AuthenticatedSession,
    DuplicateNicknameError,
    InMemoryRoomRepository,
    InvalidSpectatorPasswordError,
    InvalidPlayerTokenError,
    JoinClosedError,
    OutOfPhaseError,
    RoomFullError,
    RoomNotFoundError,
    RoomPermissionError,
)
from .schemas import (
    CreateRoomRequest,
    CreatedRoomResponse,
    HealthResponse,
    JoinedRoomResponse,
    JoinRoomRequest,
    RoomSnapshot,
)


APP_VERSION = "0.2.0"

WS_CLOSE_AUTH_REQUIRED = 4400
WS_CLOSE_INVALID_TOKEN = 4401
WS_CLOSE_INVALID_SPECTATOR = 4403
WS_CLOSE_ROOM_NOT_FOUND = 4404
WS_CLOSE_AUTH_TIMEOUT = 4408


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


async def _reject_websocket(
    websocket: WebSocket,
    *,
    code: int,
    error_code: str,
    message: str,
) -> None:
    await websocket.send_json(
        {
            "type": "error",
            "code": error_code,
            "message": message,
        }
    )
    await websocket.close(code=code)


def _authenticate_websocket(
    repository: InMemoryRoomRepository,
    room_id: str,
    payload: Any,
) -> AuthenticatedSession:
    if not isinstance(payload, dict) or payload.get("type") != "authenticate":
        raise ValueError("第一条消息必须是 authenticate")

    token = payload.get("token")
    spectator_password = payload.get("spectator_password")
    has_token = isinstance(token, str) and bool(token)
    has_password = (
        isinstance(spectator_password, str) and bool(spectator_password)
    )
    if has_token == has_password:
        raise ValueError("必须且只能提供 token 或 spectator_password")

    if has_token:
        return repository.authenticate_player(room_id, token)
    return repository.authenticate_spectator(room_id, spectator_password)


def create_app(repository: InMemoryRoomRepository | None = None) -> FastAPI:
    application = FastAPI(
        title="WolfArena API",
        version=APP_VERSION,
        description="WolfArena 九人局最小 Web 入口",
    )
    room_repository = repository or InMemoryRoomRepository()
    application.state.rooms = room_repository
    application.state.realtime = RealtimeHub(room_repository)

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
            return room_repository.create_room(
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
    async def join_room(
        room_id: str,
        payload: JoinRoomRequest,
    ) -> JoinedRoomResponse:
        try:
            joined, mutation = room_repository.join_room(
                room_id,
                payload.nickname,
            )
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except RoomFullError as error:
            raise _error(409, "ROOM_FULL", str(error)) from error
        except JoinClosedError as error:
            raise _error(409, "JOIN_CLOSED", str(error)) from error
        except DuplicateNicknameError as error:
            raise _error(409, "DUPLICATE_NICKNAME", str(error)) from error
        await application.state.realtime.broadcast_mutation(mutation)
        return joined

    @application.get(
        "/api/rooms/{room_id}",
        response_model=RoomSnapshot,
    )
    def get_room(
        room_id: str,
        player_token: str | None = Header(default=None, alias="X-Player-Token"),
    ) -> RoomSnapshot:
        try:
            return room_repository.get_snapshot(room_id, player_token)
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except InvalidPlayerTokenError as error:
            raise _error(
                status.HTTP_401_UNAUTHORIZED,
                "INVALID_PLAYER_TOKEN",
                str(error),
            ) from error

    @application.websocket("/ws/rooms/{room_id}")
    async def room_websocket(websocket: WebSocket, room_id: str) -> None:
        await websocket.accept()
        connection = None
        try:
            try:
                auth_payload = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=5.0,
                )
            except TimeoutError:
                await _reject_websocket(
                    websocket,
                    code=WS_CLOSE_AUTH_TIMEOUT,
                    error_code="AUTH_TIMEOUT",
                    message="认证超时",
                )
                return
            except JSONDecodeError:
                await _reject_websocket(
                    websocket,
                    code=WS_CLOSE_AUTH_REQUIRED,
                    error_code="AUTH_REQUIRED",
                    message="认证消息必须是 JSON",
                )
                return

            try:
                session = _authenticate_websocket(
                    room_repository,
                    room_id,
                    auth_payload,
                )
            except RoomNotFoundError as error:
                await _reject_websocket(
                    websocket,
                    code=WS_CLOSE_ROOM_NOT_FOUND,
                    error_code="ROOM_NOT_FOUND",
                    message=str(error),
                )
                return
            except InvalidPlayerTokenError as error:
                await _reject_websocket(
                    websocket,
                    code=WS_CLOSE_INVALID_TOKEN,
                    error_code="INVALID_PLAYER_TOKEN",
                    message=str(error),
                )
                return
            except InvalidSpectatorPasswordError as error:
                await _reject_websocket(
                    websocket,
                    code=WS_CLOSE_INVALID_SPECTATOR,
                    error_code="INVALID_SPECTATOR_PASSWORD",
                    message=str(error),
                )
                return
            except ValueError as error:
                await _reject_websocket(
                    websocket,
                    code=WS_CLOSE_AUTH_REQUIRED,
                    error_code="AUTH_REQUIRED",
                    message=str(error),
                )
                return

            await websocket.send_json(
                {
                    "type": "authenticated",
                    "room_id": room_id,
                    "viewer": session.snapshot.viewer.model_dump(mode="json"),
                }
            )
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "event_seq": session.room.last_event_seq,
                    "room": session.snapshot.model_dump(mode="json"),
                }
            )
            await websocket.send_json(
                {
                    "type": "phase",
                    "room_id": room_id,
                    "phase": session.room.state.phase.value,
                    "day": session.room.state.day,
                    "event_seq": session.room.last_event_seq,
                }
            )
            connection = await application.state.realtime.register(
                websocket,
                session.access,
            )

            while True:
                try:
                    payload = await websocket.receive_json()
                except JSONDecodeError:
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "INVALID_MESSAGE",
                            "message": "消息必须是合法 JSON 对象",
                        },
                    )
                    continue

                if not isinstance(payload, dict):
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "INVALID_MESSAGE",
                            "message": "消息必须是 JSON 对象",
                        },
                    )
                    continue
                if payload.get("type") == "authenticate":
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "ALREADY_AUTHENTICATED",
                            "message": "当前连接已经完成认证",
                        },
                    )
                    continue
                if payload.get("type") != "action":
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "UNSUPPORTED_MESSAGE",
                            "message": "认证后只接受 action 消息",
                        },
                    )
                    continue

                action = payload.get("action")
                if action != "start_night":
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "UNSUPPORTED_ACTION",
                            "message": "当前只实现 start_night 动作",
                        },
                    )
                    continue

                try:
                    mutation = room_repository.start_night(session.access)
                except RoomPermissionError as error:
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "ACTION_FORBIDDEN",
                            "message": str(error),
                        },
                    )
                    continue
                except OutOfPhaseError as error:
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "OUT_OF_PHASE",
                            "message": str(error),
                        },
                    )
                    continue
                await application.state.realtime.broadcast_mutation(mutation)
                await application.state.realtime.send(
                    connection,
                    {
                        "type": "action_result",
                        "action": "start_night",
                        "ok": True,
                        "phase": mutation.room.state.phase.value,
                        "event_seq": mutation.current_event_seq,
                    },
                )
        except WebSocketDisconnect:
            pass
        finally:
            if connection is not None:
                await application.state.realtime.unregister(connection)

    return application


app = create_app()
