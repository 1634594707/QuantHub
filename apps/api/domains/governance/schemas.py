from __future__ import annotations

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=200)
    roles: list[str] = Field(default_factory=lambda: ["viewer"])


class UserRolesUpdate(BaseModel):
    roles: list[str] = Field(..., min_length=1)


class UserStatusUpdate(BaseModel):
    active: bool


class TokenCreate(BaseModel):
    user_id: str = Field(..., min_length=1)
    label: str = Field(..., min_length=1, max_length=200)
    expires_at: float | None = None
