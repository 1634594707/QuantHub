from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from . import service
from .schemas import AlertRuleCreate, AlertRuleUpdate

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _user_id(request: Request) -> str:
    return str(request.state.principal["id"])


@router.get("/rules")
def list_rules(request: Request) -> dict:
    return service.list_rules(_user_id(request))


@router.post("/rules", status_code=201)
def create_rule(req: AlertRuleCreate, request: Request) -> dict:
    return {"ok": True, "rule": service.create_rule(_user_id(request), req.model_dump())}


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: str, req: AlertRuleUpdate, request: Request) -> dict:
    rule = service.update_rule(rule_id, _user_id(request), req.model_dump(exclude_unset=True))
    if rule is None:
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    return {"ok": True, "rule": rule}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str, request: Request) -> dict:
    if not service.delete_rule(rule_id, _user_id(request)):
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    return {"ok": True}


@router.post("/rules/{rule_id}/check")
def check_rule(rule_id: str, request: Request) -> dict:
    rule = service.get_rule(rule_id, _user_id(request))
    if rule is None:
        raise HTTPException(status_code=404, detail="提醒规则不存在")
    return service.check_rule(rule, force=True)


@router.get("/events")
def list_events(
    request: Request,
    pending_only: bool = False,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    return service.list_events(_user_id(request), pending_only=pending_only, limit=limit)


@router.post("/events/{event_id}/acknowledge")
def acknowledge_event(event_id: str, request: Request) -> dict:
    event = service.acknowledge_event(event_id, _user_id(request))
    if event is None:
        raise HTTPException(status_code=404, detail="提醒记录不存在")
    return {"ok": True, "event": event}


@router.post("/check")
def check_all_rules() -> dict:
    return service.check_all_rules(force=True)
