from __future__ import annotations

from fastapi import APIRouter

from . import service
from .schemas import (
    ApiKeyUpdate,
    LLMSettingsUpdate,
    NotificationChannel,
    NotificationChannelUpdate,
    NotificationEnabledUpdate,
)

router = APIRouter(prefix="/config", tags=["settings"])


@router.get("/apikey")
def get_api_key_status() -> dict:
    return service.credential_status()


@router.post("/apikey")
def set_api_key(req: ApiKeyUpdate) -> dict:
    return service.update_credential(req.api_key)


@router.get("/llm")
def get_llm_settings() -> dict:
    return service.credential_status()


@router.put("/llm")
def update_llm_settings(req: LLMSettingsUpdate) -> dict:
    try:
        return service.update_llm_settings(req.model_dump())
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/llm/key")
def delete_llm_key() -> dict:
    return service.remove_credential()


@router.post("/llm/test")
def test_llm_connection() -> dict:
    try:
        return service.test_llm_connection()
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/status")
def get_system_status() -> dict:
    return service.system_status()


@router.get("/notifications")
def get_notifications() -> dict:
    return service.notification_status()


@router.patch("/notifications")
def update_notifications(req: NotificationEnabledUpdate) -> dict:
    return service.update_notification_enabled(req.enabled)


@router.put("/notifications/{channel}")
def update_notification_channel(
    channel: NotificationChannel, req: NotificationChannelUpdate
) -> dict:
    return service.update_notification_channel(channel, req.model_dump(exclude_none=True))


@router.post("/notifications/{channel}/test")
def test_notification_channel(channel: NotificationChannel) -> dict:
    try:
        return service.test_notification_channel(channel)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail=str(exc)) from exc
