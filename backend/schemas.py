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
    seed: int = Field(strict=True)
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


class ViewerPlayer(ApiModel):
    player_id: str
    seat: int
    name: str
    role: str
    is_alive: bool


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


class RoomSnapshot(ApiModel):
    room_id: str
    phase: str
    day: int
    human_count: int
    max_humans: int
    viewer: ViewerPlayer
    players: list[PublicPlayer]
    visible_events: list[PublicEvent]


class CreatedRoomResponse(ApiModel):
    room_id: str
    player_token: str
    room: RoomSnapshot


class JoinedRoomResponse(ApiModel):
    player_token: str
    room: RoomSnapshot
