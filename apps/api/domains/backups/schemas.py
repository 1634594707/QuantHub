from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class BackupActionRequest(BaseModel):
    actor: str = Field(default="local-user", min_length=1, max_length=100)

    @field_validator("actor")
    @classmethod
    def normalize_actor(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("actor 不能为空")
        return normalized


class BackupRestoreRequest(BackupActionRequest):
    confirm_name: str = Field(min_length=1, max_length=255)


class BackupRetentionRequest(BackupActionRequest):
    keep: int = Field(default=14, ge=1, le=365)


class BackupRetentionApplyRequest(BackupRetentionRequest):
    confirm_files: list[str]
