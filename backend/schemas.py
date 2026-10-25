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
    deadline_kind: Literal["last_words", "speech", "self_destruct"] | None = None
    remaining_ms: int | None = Field(default=None, ge=0)
    human_count: int
    max_humans: int
    viewer: ViewerIdentity
    players: list[PublicPlayer]
    visible_events: list[PublicEvent]
    available_actions: list[ActionView] = Field(default_factory=list)


class CreatedRoomResponse(ApiModel):
    room_id: str
    player_token: str
    spectator_password: str
    room: RoomSnapshot


class JoinedRoomResponse(ApiModel):
    player_token: str
    room: RoomSnapshot
