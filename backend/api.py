"""Minimal FastAPI entry point for WolfArena."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from json import JSONDecodeError
import os
from pathlib import Path
from secrets import randbits
import subprocess
import time
from typing import Any

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Query,
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
    _load_private_env,
)
from .realtime import RealtimeHub
from .strategy_library import StrategyError, StrategyToolError, search_strategy
from .strategy_admin import (
    approve,
    evaluate,
    evaluation_for,
    list_library,
    reject,
    reviewer_authorized,
    rollback,
    submit_candidate,
)
from .training import (
    TrainingToolError,
    rollout_faction_win_rates,
    training_metrics,
    training_models,
)
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
    SeatUnavailableError,
)
from .timers import RoomTimerService
from .vision_review import review_transcript
from .schemas import (
    ActionRequest,
    AvailableSeatsResponse,
    ChatRequest,
    CreateRoomRequest,
    CreatedRoomResponse,
    HealthResponse,
    JoinedRoomResponse,
    JoinRoomRequest,
    RoomSnapshot,
    ScreenshotReviewRequest,
    StrategyApproveRequest,
    StrategyEvaluateRequest,
    StrategyRejectRequest,
    StrategyRollbackRequest,
    StrategySearchRequest,
    StrategySubmitRequest,
)


APP_VERSION = "0.6.0"


def _resolve_commit() -> str:
    """Best-effort commit id so /health can prove which build is running."""

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


APP_COMMIT = _resolve_commit()

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
    strategy_root: Path | None = None,
) -> FastAPI:
    _load_private_env()
    room_repository = repository or InMemoryRoomRepository()
    realtime = RealtimeHub(room_repository)
    timer_service = RoomTimerService(room_repository, realtime)
    resolved_strategy_root = strategy_root or (
        Path(__file__).resolve().parent.parent / "strategy_library"
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        timer_service.start()
        try:
            yield
        finally:
            await timer_service.stop()

    application = FastAPI(
        title="WolfArena API",
        version=APP_VERSION,
        description="WolfArena 九人局最小 Web 入口",
        lifespan=lifespan,
    )
    application.state.rooms = room_repository
    application.state.realtime = realtime
    application.state.timer_service = timer_service
    application.state.ai_provider = ai_provider or DeepSeekCandidateProvider(
        DeepSeekSettings.from_environment()
    )
    application.state.chat_times = {}
    application.state.chat_min_interval = 3.0

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="wolfarena-api",
            version=APP_VERSION,
            commit=APP_COMMIT,
        )

    @application.post(
        "/api/rooms",
        response_model=CreatedRoomResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_room(payload: CreateRoomRequest) -> CreatedRoomResponse:
        try:
            return room_repository.create_room(
                seed=payload.seed if payload.seed is not None else randbits(63),
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
                seat=payload.seat,
            )
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except RoomFullError as error:
            raise _error(409, "ROOM_FULL", str(error)) from error
        except JoinClosedError as error:
            raise _error(409, "JOIN_CLOSED", str(error)) from error
        except DuplicateNicknameError as error:
            raise _error(409, "DUPLICATE_NICKNAME", str(error)) from error
        except SeatUnavailableError as error:
            raise _error(409, "SEAT_UNAVAILABLE", str(error)) from error
        await application.state.realtime.broadcast_mutation(mutation)
        return joined

    @application.get(
        "/api/rooms/{room_id}/seats",
        response_model=AvailableSeatsResponse,
    )
    def room_seats(room_id: str) -> AvailableSeatsResponse:
        try:
            return AvailableSeatsResponse(
                room_id=room_id,
                available_seats=room_repository.available_seats(room_id),
            )
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error

    @application.post("/api/strategy/search")
    def strategy_search_tool(payload: StrategySearchRequest):
        try:
            return search_strategy(
                root=resolved_strategy_root,
                query=payload.query,
                role=payload.role,
                phase=payload.phase,
                limit=payload.limit,
            )
        except StrategyToolError as error:
            raise _error(
                422,
                "STRATEGY_TOOL_REJECTED",
                str(error),
            ) from error

    def _require_reviewer(header_token: str | None) -> None:
        env_token = os.environ.get("WOLFARENA_REVIEWER_TOKEN")
        if not reviewer_authorized(header_token, env_token):
            raise _error(
                401,
                "REVIEWER_UNAUTHORIZED",
                "审核凭证无效或服务端未配置 WOLFARENA_REVIEWER_TOKEN",
            )

    @application.get("/api/strategy/library")
    def strategy_library_index():
        return list_library(strategy_root=resolved_strategy_root)

    @application.post(
        "/api/strategy/candidates",
        status_code=status.HTTP_201_CREATED,
    )
    def strategy_submit(payload: StrategySubmitRequest):
        try:
            return submit_candidate(
                payload.model_dump(),
                strategy_root=resolved_strategy_root,
            )
        except (ValueError, StrategyError) as error:
            raise _error(422, "STRATEGY_REJECTED", str(error)) from error

    @application.get("/api/strategy/candidates/{candidate_id}/evaluation")
    def strategy_evaluation(candidate_id: str):
        result = evaluation_for(candidate_id)
        if result is None:
            raise _error(404, "EVALUATION_NOT_FOUND", "该候选还没有评测证据")
        return result

    @application.post("/api/strategy/candidates/{candidate_id}/evaluate")
    def strategy_evaluate(
        candidate_id: str,
        payload: StrategyEvaluateRequest,
    ):
        try:
            return evaluate(
                candidate_id,
                strategy_root=resolved_strategy_root,
                seed_start=payload.seed_start,
                games=payload.games,
            )
        except ValueError as error:
            raise _error(404, "CANDIDATE_NOT_FOUND", str(error)) from error

    @application.post("/api/strategy/candidates/{candidate_id}/approve")
    def strategy_approve(
        candidate_id: str,
        payload: StrategyApproveRequest,
        reviewer_token: str | None = Header(
            default=None, alias="X-Reviewer-Token"
        ),
    ):
        _require_reviewer(reviewer_token)
        try:
            return approve(
                candidate_id,
                payload.reviewer,
                strategy_root=resolved_strategy_root,
                skip_evaluation=payload.skip_evaluation,
            )
        except ValueError as error:
            raise _error(422, "APPROVE_REJECTED", str(error)) from error
        except StrategyError as error:
            raise _error(404, "CANDIDATE_NOT_FOUND", str(error)) from error

    @application.post("/api/strategy/candidates/{candidate_id}/reject")
    def strategy_reject(
        candidate_id: str,
        payload: StrategyRejectRequest,
        reviewer_token: str | None = Header(
            default=None, alias="X-Reviewer-Token"
        ),
    ):
        _require_reviewer(reviewer_token)
        try:
            return reject(
                candidate_id,
                payload.reason,
                strategy_root=resolved_strategy_root,
            )
        except StrategyError as error:
            raise _error(404, "CANDIDATE_NOT_FOUND", str(error)) from error

    @application.post("/api/strategy/validated/{strategy_id}/rollback")
    def strategy_rollback(
        strategy_id: str,
        payload: StrategyRollbackRequest,
        reviewer_token: str | None = Header(
            default=None, alias="X-Reviewer-Token"
        ),
    ):
        _require_reviewer(reviewer_token)
        try:
            return rollback(
                strategy_id,
                payload.reason,
                strategy_root=resolved_strategy_root,
            )
        except StrategyError as error:
            raise _error(404, "STRATEGY_NOT_FOUND", str(error)) from error

    @application.post("/api/review/screenshot")
    def screenshot_review(payload: ScreenshotReviewRequest):
        return review_transcript(payload.lines, day=payload.day)

    @application.post("/api/rooms/{room_id}/chat")
    async def room_chat(
        room_id: str,
        payload: ChatRequest,
        player_token: str | None = Header(default=None, alias="X-Player-Token"),
    ):
        try:
            session = room_repository.authenticate_player(room_id, player_token)
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except InvalidPlayerTokenError as error:
            raise _error(401, "INVALID_PLAYER_TOKEN", str(error)) from error

        now = time.time()
        chat_times = application.state.chat_times
        if now - chat_times.get(room_id, 0.0) < application.state.chat_min_interval:
            raise _error(429, "CHAT_RATE_LIMITED", "发言太快，稍等一下")
        chat_times[room_id] = now

        snapshot = room_repository.snapshot_for_access(
            session.room,
            session.access,
        )
        ai_seats = [
            player
            for player in snapshot.players
            if not player.is_human and player.is_alive
        ]
        if not ai_seats:
            raise _error(409, "NO_AI_PLAYER", "当前没有可对话的 AI 玩家")
        target = next(
            (
                player
                for player in ai_seats
                if payload.seat is not None and player.seat == payload.seat
            ),
            ai_seats[0],
        )
        roster = [
            f"{player.seat}号{player.name}"
            for player in snapshot.players
            if player.is_alive
        ]
        recent = [
            str(event.data.get("content", ""))
            for event in snapshot.visible_events
            if event.event_type == "PUBLIC_SPEECH"
            and event.data.get("content")
        ][-3:]

        reply = f"{target.seat} 号：我先记住你的说法，后面投票再判断。"
        source = "fallback"
        provider = application.state.ai_provider
        chat_reply = getattr(provider, "chat_reply", None)
        if callable(chat_reply):
            try:
                text = await chat_reply(
                    seat=target.seat,
                    day=snapshot.day,
                    phase=snapshot.phase,
                    roster=roster,
                    recent=recent,
                    message=payload.message,
                )
                cleaned = " ".join(str(text).split())[:140]
                if cleaned:
                    reply = cleaned
                    source = "deepseek"
            except Exception:
                source = "fallback"

        return {
            "room_id": room_id,
            "seat": target.seat,
            "name": target.name,
            "reply": reply,
            "source": source,
        }

    @application.get("/api/training/models")
    def list_training_models():
        return {"models": training_models()}

    @application.get("/api/training/models/{model_id}")
    def get_training_model(model_id: str):
        for model in training_models():
            if model["model_id"] == model_id:
                return model
        raise _error(404, "MODEL_NOT_FOUND", f"未知模型：{model_id}")

    @application.get("/api/training/metrics")
    def list_training_metrics(
        model_id: str | None = Query(default=None),
    ):
        metrics = training_metrics()
        if model_id is not None:
            for metric in metrics:
                if metric["model_id"] == model_id:
                    return metric
            raise _error(404, "MODEL_NOT_FOUND", f"未知模型：{model_id}")
        return {"metrics": metrics}

    @application.get("/api/training/rollout")
    def training_rollout(
        policy: str = Query(...),
        seed_start: int = Query(...),
        games: int = Query(...),
        baseline_policy: str = Query(default="l0"),
    ):
        try:
            return rollout_faction_win_rates(
                policy=policy,
                seed_start=seed_start,
                games=games,
                baseline_policy=baseline_policy,
            )
        except TrainingToolError as error:
            raise _error(
                422,
                "TRAINING_TOOL_REJECTED",
                str(error),
            ) from error

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
            mutation = room_repository.execute_action_and_advance_ai(
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
        "/api/rooms/{room_id}/continue",
        response_model=RoomSnapshot,
    )
    async def continue_room(
        room_id: str,
        player_token: str | None = Header(default=None, alias="X-Player-Token"),
    ) -> RoomSnapshot:
        try:
            session = room_repository.authenticate_player(room_id, player_token)
        except RoomNotFoundError as error:
            raise _error(404, "ROOM_NOT_FOUND", str(error)) from error
        except InvalidPlayerTokenError as error:
            raise _error(401, "INVALID_PLAYER_TOKEN", str(error)) from error

        try:
            mutation = room_repository.request_continue(
                room_id,
                session.access,
            )
        except RoomPermissionError as error:
            raise _error(403, "ACTION_FORBIDDEN", str(error)) from error

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
            mutation = room_repository.execute_action_and_advance_ai(
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
                    mutation = room_repository.execute_action_and_advance_ai(
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

        class NoCacheStaticFiles(StaticFiles):
            """Force revalidation so a deploy is visible without hard refresh."""

            async def get_response(self, path, scope):
                response = await super().get_response(path, scope)
                response.headers["Cache-Control"] = "no-cache, must-revalidate"
                return response

        application.mount(
            "/",
            NoCacheStaticFiles(directory=frontend_dist, html=True),
            name="frontend",
        )

    return application


app = create_app()
