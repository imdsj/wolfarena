"""HTTP request and response models for the WolfArena web entry."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    """Shared strict model configuration."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HealthResponse(ApiModel):
    status: Literal["ok"]
    service: str
    version: str
    commit: str = "unknown"


class CreateRoomRequest(ApiModel):
    seed: int | None = Field(default=None, strict=True)
    human_count: int = Field(default=1, strict=True, ge=1, le=3)
    max_humans: int = Field(default=3, strict=True, ge=1, le=3)
    nickname: str = Field(min_length=1, max_length=32)

    @field_validator("nickname")
    @classmethod
    def nickname_must_be_visible(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("昵称不能为空")
        return value


class JoinRoomRequest(ApiModel):
    nickname: str = Field(min_length=1, max_length=32)
    seat: int | None = Field(default=None, ge=1, le=9)

    @field_validator("nickname")
    @classmethod
    def nickname_must_be_visible(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("昵称不能为空")
        return value


class ViewerIdentity(ApiModel):
    kind: Literal["player", "spectator"]
    player_id: str | None
    seat: int | None
    name: str
    role: str | None
    is_alive: bool | None
    is_host: bool


class PublicPlayer(ApiModel):
    player_id: str
    seat: int
    name: str
    is_human: bool
    is_alive: bool
    archetype: str | None = None


class DecisionTraceView(ApiModel):
    day: int
    phase: str
    action: str
    target_id: str | None
    choice: str | None
    persona: str
    strategy_id: str
    rationale: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    evidence_event_ids: list[int] = Field(default_factory=list)
    tactic_ids: list[str] = Field(default_factory=list)


class AgentInsight(ApiModel):
    player_id: str
    seat: int
    name: str
    archetype: str | None
    current_plan: str | None = None
    decision_traces: list[DecisionTraceView] = Field(default_factory=list)


class PublicEvent(ApiModel):
    event_seq: int
    event_type: str
    day: int
    phase: str
    actor_id: str | None
    target_id: str | None
    visibility: str
    data: dict[str, Any]


class ActionView(ApiModel):
    action: str
    label: str
    target_ids: list[str] = Field(default_factory=list)
    choices: list[str] = Field(default_factory=list)
    requires_content: bool = False
    requires_target: bool = False
    allow_no_target: bool = False


class ActionRequest(ApiModel):
    action: str = Field(min_length=1, max_length=64)
    target_id: str | None = Field(default=None, max_length=64)
    content: str | None = Field(default=None, max_length=500)
    choice: str | None = Field(default=None, max_length=32)


class RoomSnapshot(ApiModel):
    room_id: str
    phase: str
    day: int
    server_time: float = Field(ge=0)
    deadline_at: float | None = Field(default=None, ge=0)
    deadline_kind: (
        Literal[
            "last_words",
            "speech",
            "self_destruct",
            "human_action",
            "phase_pace",
        ]
        | None
    ) = None
    remaining_ms: int | None = Field(default=None, ge=0)
    witch_kill_target_visible: bool = False
    witch_kill_target_id: str | None = None
    human_count: int
    max_humans: int
    viewer: ViewerIdentity
    players: list[PublicPlayer]
    visible_events: list[PublicEvent]
    available_actions: list[ActionView] = Field(default_factory=list)
    available_seats: list[int] = Field(default_factory=list)
    announcements: list[str] = Field(default_factory=list)
    last_night_summary: str | None = None
    awaiting_continue: bool = False
    agent_insights: list[AgentInsight] = Field(default_factory=list)


class AvailableSeatsResponse(ApiModel):
    room_id: str
    available_seats: list[int]


class StrategySearchRequest(ApiModel):
    query: str = Field(default="", max_length=200)
    role: Literal["werewolf", "villager", "seer", "witch", "hunter"] | None = None
    phase: str | None = Field(default=None, max_length=64)
    limit: int = Field(default=5, ge=1, le=20)


class ChatRequest(ApiModel):
    message: str = Field(min_length=1, max_length=200)
    seat: int | None = Field(default=None, ge=1, le=9)


class StrategySubmitRequest(ApiModel):
    title: str = Field(min_length=1, max_length=120)
    role: Literal["werewolf", "villager", "seer", "witch", "hunter"]
    phase: str = Field(default="ANY", max_length=64)
    action: str = Field(min_length=1, max_length=64)
    trigger: str = Field(min_length=1, max_length=600)
    recommendation: str = Field(min_length=1, max_length=600)
    rationale: str = Field(min_length=1, max_length=1000)
    risk: str = Field(min_length=1, max_length=600)
    directive: str | None = Field(default=None, max_length=64)
    created_by: str = Field(min_length=1, max_length=64)


class StrategyEvaluateRequest(ApiModel):
    seed_start: int = Field(default=7000, ge=0)
    games: int = Field(default=200, ge=200, le=2000)


class StrategyApproveRequest(ApiModel):
    reviewer: str = Field(min_length=1, max_length=64)


class StrategyRejectRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=400)


class StrategyRollbackRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=400)


class ScreenshotReviewRequest(ApiModel):
    day: int = Field(default=1, ge=1, le=20)
    lines: list[str] = Field(default_factory=list, max_length=200)


class CreatedRoomResponse(ApiModel):
    room_id: str
    player_token: str
    spectator_password: str
    room: RoomSnapshot


class JoinedRoomResponse(ApiModel):
    player_token: str
    room: RoomSnapshot
