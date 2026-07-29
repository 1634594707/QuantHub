from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from . import repository
from .schemas import TokenCreate, UserCreate, UserRolesUpdate, UserStatusUpdate

router = APIRouter(prefix="/auth", tags=["governance"])


@router.get("/session")
def session(request: Request) -> dict:
    return {"ok": True, "user": request.state.principal}


@router.get("/users")
def users() -> dict:
    items = repository.list_users()
    return {"ok": True, "count": len(items), "users": items}


@router.get("/roles")
def roles() -> dict:
    items = repository.list_roles()
    return {"ok": True, "count": len(items), "roles": items}


@router.post("/users")
def create_user(req: UserCreate) -> dict:
    try:
        user = repository.create_user(req.username, req.display_name, req.roles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "user": user}


@router.put("/users/{user_id}/roles")
def update_user_roles(user_id: str, req: UserRolesUpdate) -> dict:
    try:
        user = repository.update_roles(user_id, req.roles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True, "user": user}


@router.patch("/users/{user_id}/status")
def update_user_status(user_id: str, req: UserStatusUpdate) -> dict:
    user = repository.set_user_active(user_id, req.active)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"ok": True, "user": user}


@router.post("/tokens")
def create_api_token(req: TokenCreate) -> dict:
    try:
        token = repository.create_token(req.user_id, req.label, req.expires_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "token": token}


@router.get("/tokens")
def tokens() -> dict:
    items = repository.list_tokens()
    return {"ok": True, "count": len(items), "tokens": items}


@router.delete("/tokens/{token_id}")
def revoke_api_token(token_id: str) -> dict:
    token = repository.revoke_token(token_id)
    if token is None:
        raise HTTPException(status_code=404, detail="令牌不存在")
    return {"ok": True, "token": token}


@router.get("/audit")
def audit(
    limit: int = Query(default=200, ge=1, le=1000), cursor: str | None = None
) -> dict:
    try:
        page = repository.list_audit_page(limit=limit, cursor=cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "ok": True,
        "count": len(page["items"]),
        "total": page["total"],
        "next_cursor": page["next_cursor"],
        "audit": page["items"],
    }
