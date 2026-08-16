from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request

from apps.api import store
from packages.financial_data import CompanyEvent, InstrumentRelationship, MacroEvent

from . import service

router = APIRouter(prefix="/research-data", tags=["research-data"])


def _owner_id(request: Request) -> str:
    principal = getattr(request.state, "principal", None) or {}
    return str(principal.get("id") or "local-user")


@router.get("/financial-statements")
def financial_statements(
    instrument_id: str,
    available_as_of: datetime | None = Query(default=None),
    statement_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    items = store.list_financial_statements(
        instrument_id,
        available_as_of=available_as_of or datetime.now(UTC),
        statement_type=statement_type,
        limit=limit,
    )
    return {"ok": True, "count": len(items), "items": items}


@router.get("/valuations")
def valuations(
    instrument_id: str,
    as_of: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    items = store.list_valuation_snapshots(
        instrument_id, as_of=as_of or datetime.now(UTC), limit=limit
    )
    return {"ok": True, "count": len(items), "items": items}


@router.get("/company-events")
def company_events(
    instrument_id: str,
    available_as_of: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    items = store.list_company_events(
        instrument_id, available_as_of=available_as_of or datetime.now(UTC), limit=limit
    )
    return {"ok": True, "count": len(items), "items": items}


@router.post("/company-events", status_code=201)
def create_company_event(event: CompanyEvent) -> dict:
    return {"ok": True, "inserted": service.save_company_event(event), "event": event}


@router.get("/macro-events")
def macro_events(
    available_as_of: datetime | None = Query(default=None),
    region: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    items = store.list_macro_events(
        available_as_of=available_as_of or datetime.now(UTC), region=region, limit=limit
    )
    return {"ok": True, "count": len(items), "items": items}


@router.post("/macro-events", status_code=201)
def create_macro_event(event: MacroEvent) -> dict:
    return {"ok": True, "inserted": service.save_macro_event(event), "event": event}


@router.get("/relationships")
def relationships(
    instrument_id: str,
    request: Request,
    as_of: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    items = store.list_instrument_relationships(
        instrument_id,
        as_of=as_of or datetime.now(UTC),
        limit=limit,
        owner_id=_owner_id(request),
    )
    return {"ok": True, "count": len(items), "items": items}


@router.post("/relationships", status_code=201)
def create_relationship(relationship: InstrumentRelationship, request: Request) -> dict:
    return {
        "ok": True,
        "inserted": service.save_relationship(relationship, owner_id=_owner_id(request)),
        "relationship": relationship,
    }


@router.get("/transmissions")
def transmissions(
    instrument_id: str,
    request: Request,
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict:
    items = store.list_macro_transmissions(instrument_id, limit=limit, owner_id=_owner_id(request))
    return {"ok": True, "count": len(items), "items": items}
