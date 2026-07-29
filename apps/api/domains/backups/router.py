"""数据库备份路由：/backups/*。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import service
from .schemas import (
    BackupActionRequest,
    BackupRestoreRequest,
    BackupRetentionApplyRequest,
    BackupRetentionRequest,
)

router = APIRouter(prefix="/backups", tags=["backups"])


def _raise_backup_error(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, FileExistsError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise exc


@router.get("/status")
def get_status() -> dict:
    return service.status()


@router.get("")
def list_backups() -> dict:
    return service.list_backups()


@router.post("")
def create_backup(payload: BackupActionRequest) -> dict:
    try:
        return service.create_backup(actor=payload.actor)
    except Exception as exc:
        _raise_backup_error(exc)


@router.post("/retention/preview")
def preview_retention(payload: BackupRetentionRequest) -> dict:
    try:
        return service.retention_preview(keep=payload.keep, actor=payload.actor)
    except Exception as exc:
        _raise_backup_error(exc)


@router.post("/retention/apply")
def apply_retention(payload: BackupRetentionApplyRequest) -> dict:
    try:
        return service.retention_apply(
            keep=payload.keep,
            confirm_files=payload.confirm_files,
            actor=payload.actor,
        )
    except Exception as exc:
        _raise_backup_error(exc)


@router.post("/{name}/verify")
def verify_backup(name: str, payload: BackupActionRequest) -> dict:
    try:
        return service.verify_backup(name, actor=payload.actor)
    except Exception as exc:
        _raise_backup_error(exc)


@router.post("/{name}/restore")
def restore_backup(name: str, payload: BackupRestoreRequest) -> dict:
    try:
        return service.restore_backup(
            name,
            confirm_name=payload.confirm_name,
            actor=payload.actor,
        )
    except Exception as exc:
        _raise_backup_error(exc)
