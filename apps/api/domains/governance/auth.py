from __future__ import annotations

import os

from fastapi import Request

from . import repository


def auth_required() -> bool:
    mode = os.environ.get("QUANTHUB_DEPLOYMENT_MODE", "local")
    return os.environ.get("QUANTHUB_AUTH_REQUIRED") == "1" or mode in {"lan", "postgresql"}


def authenticate(request: Request) -> dict | None:
    if not auth_required():
        return repository.get_user("local-user")
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return None
    token = authorization[len(prefix) :].strip()
    bootstrap = os.environ.get("QUANTHUB_BOOTSTRAP_ADMIN_TOKEN", "")
    if bootstrap and token == bootstrap:
        return repository.get_user("local-user")
    return repository.principal_by_token(token)


def required_permission(method: str, path: str) -> str:
    if path == "/auth/session":
        return "read"
    if path.startswith("/auth"):
        return "users.manage"
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    mappings = (
        ("/signals", "signals.write"),
        ("/ledger", "ledger.write"),
        ("/strategy-lab", "strategy.write"),
        ("/strategies", "strategy.write"),
        ("/simulation", "simulation.write"),
        ("/research", "research.write"),
        ("/alerts", "research.write"),
        ("/portfolio", "portfolio.write"),
        ("/market/watchlist", "portfolio.write"),
        ("/automation", "automation.manage"),
        ("/backups", "backups.manage"),
        ("/config", "config.manage"),
        ("/incidents", "config.manage"),
        ("/instruments", "portfolio.write"),
        ("/market-data", "research.write"),
        ("/market", "portfolio.write"),
        ("/news", "research.write"),
        ("/tasks", "research.write"),
        ("/ensemble", "research.write"),
    )
    for prefix, permission in mappings:
        if path.startswith(prefix):
            return permission
    return "research.write"
