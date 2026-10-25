"""Minimal FastAPI entry point for WolfArena."""

from __future__ import annotations

import asyncio
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .actions import ActionUnavailableError, ActionValidationError
from .ai_provider import (
    AIActionResponse,
    CandidateProvider,
    DeepSeekCandidateProvider,
    DeepSeekSettings,
)
from .realtime import RealtimeHub
from .rooms import (
    AuthenticatedSession,
    DuplicateNicknameError,
    InMemoryRoomRepository,
    InvalidSpectatorPasswordError,
    InvalidPlayerTokenError,
    JoinClosedError,
    RoomFullError,
    RoomNotFoundError,
    RoomPermissionError,
)
from .schemas import (
    ActionRequest,
    CreateRoomRequest,
    CreatedRoomResponse,
    HealthResponse,
    JoinedRoomResponse,
    JoinRoomRequest,
    RoomSnapshot,
)


APP_VERSION = "0.3.0"

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


def create_app(
    repository: InMemoryRoomRepository | None = None,
    ai_provider: CandidateProvider | None = None,
) -> FastAPI:
    application = FastAPI(
        title="WolfArena API",
        version=APP_VERSION,
        description="WolfArena 九人局最小 Web 入口",
    )
    room_repository = repository or InMemoryRoomRepository()
    application.state.rooms = room_repository
    application.state.realtime = RealtimeHub(room_repository)
    application.state.ai_provider = ai_provider or DeepSeekCandidateProvider(
        DeepSeekSettings.from_environment()
    )

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

    @application.post(
        "/api/rooms/{room_id}/actions",
        response_model=RoomSnapshot,
    )
    async def execute_room_action(
        room_id: str,
        payload: ActionRequest,
        player_token: str | None = Header(default=None, alias="X-Player-Token"),
    ) -> RoomSnapshot:
        try:
            session = room_repository.authenticate_player(room_id, player_token)
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except InvalidPlayerTokenError as error:
            raise _error(401, "INVALID_PLAYER_TOKEN", str(error)) from error

        try:
            mutation = room_repository.execute_action(
                session.access,
                payload,
            )
        except ActionUnavailableError as error:
            raise _error(409, "ACTION_UNAVAILABLE", str(error)) from error
        except ActionValidationError as error:
            raise _error(422, "ACTION_INVALID", str(error)) from error
        except RoomPermissionError as error:
            raise _error(403, "ACTION_FORBIDDEN", str(error)) from error
        except ValueError as error:
            raise _error(409, "ACTION_REJECTED", str(error)) from error

        await application.state.realtime.broadcast_mutation(mutation)
        return room_repository.snapshot_for_access(
            mutation.room,
            session.access,
        )

    @application.post(
        "/api/rooms/{room_id}/ai-action",
        response_model=AIActionResponse,
    )
    async def ai_action(
        room_id: str,
        player_token: str | None = Header(default=None, alias="X-Player-Token"),
    ) -> AIActionResponse:
        try:
            session = room_repository.authenticate_player(room_id, player_token)
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except InvalidPlayerTokenError as error:
            raise _error(401, "INVALID_PLAYER_TOKEN", str(error)) from error

        context = room_repository.ai_action_context(session.access)
        if not context.legal_actions:
            rejection = room_repository.record_ai_rejection(
                session.access,
                reason="no_legal_actions",
                candidate_action="none",
                candidate_target_id=None,
            )
            await application.state.realtime.broadcast_mutation(rejection)
            raise _error(409, "AI_NO_LEGAL_ACTION", "当前阶段没有可执行动作")

        decision = await application.state.ai_provider.propose(
            context.snapshot,
            legal_actions=context.legal_actions,
            valid_target_ids=context.valid_target_ids,
        )
        candidate = decision.candidate
        if candidate.action not in context.legal_actions:
            rejection = room_repository.record_ai_rejection(
                session.access,
                reason="action_not_legal",
                candidate_action=candidate.action,
                candidate_target_id=candidate.target_id,
            )
            await application.state.realtime.broadcast_mutation(rejection)
            raise _error(
                422,
                "AI_ACTION_INVALID",
                "模型候选动作不在服务端合法动作中",
            )
        if (
            candidate.target_id is not None
            and candidate.target_id not in context.valid_target_ids
        ):
            rejection = room_repository.record_ai_rejection(
                session.access,
                reason="target_not_valid",
                candidate_action=candidate.action,
                candidate_target_id=candidate.target_id,
            )
            await application.state.realtime.broadcast_mutation(rejection)
            raise _error(
                422,
                "AI_TARGET_INVALID",
                "模型候选目标不在服务端合法目标中",
            )

        if decision.source == "fallback":
            fallback = room_repository.record_ai_fallback(
                session.access,
                reason=decision.fallback_reason or "unknown_fallback",
                action=candidate.action,
            )
            await application.state.realtime.broadcast_mutation(fallback)

        action_request = ActionRequest(
            action=candidate.action,
            target_id=candidate.target_id,
            content=candidate.content,
        )
        try:
            mutation = room_repository.execute_action(
                session.access,
                action_request,
            )
        except ActionValidationError as error:
            raise _error(422, "AI_ACTION_INVALID", str(error)) from error
        except ActionUnavailableError as error:
            raise _error(409, "OUT_OF_PHASE", str(error)) from error
        except RoomPermissionError as error:
            raise _error(403, "ACTION_FORBIDDEN", str(error)) from error
        except ValueError as error:
            raise _error(409, "ACTION_REJECTED", str(error)) from error

        await application.state.realtime.broadcast_mutation(mutation)
        return AIActionResponse(
            decision=decision,
            executed=True,
            phase=mutation.room.state.phase.value,
            event_seq=mutation.current_event_seq,
        )

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

                try:
                    action_payload = {
                        key: value
                        for key, value in payload.items()
                        if key != "type"
                    }
                    action_request = ActionRequest.model_validate(action_payload)
                    mutation = room_repository.execute_action(
                        session.access,
                        action_request,
                    )
                except ValidationError as error:
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "ACTION_INVALID",
                            "message": "动作请求字段校验失败",
                        },
                    )
                    continue
                except ActionValidationError as error:
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "ACTION_INVALID",
                            "message": str(error),
                        },
                    )
                    continue
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
                except ActionUnavailableError as error:
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "ACTION_UNAVAILABLE",
                            "message": str(error),
                        },
                    )
                    continue
                except ValueError as error:
                    await application.state.realtime.send(
                        connection,
                        {
                            "type": "error",
                            "code": "ACTION_REJECTED",
                            "message": str(error),
                        },
                    )
                    continue
                await application.state.realtime.broadcast_mutation(mutation)
                await application.state.realtime.send(
                    connection,
                    {
                        "type": "action_result",
                        "action": action_request.action,
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

    frontend_dist = (
        Path(__file__).resolve().parent.parent / "frontend" / "dist"
    )
    if frontend_dist.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=frontend_dist, html=True),
            name="frontend",
        )

    return application


app = create_app()
