from __future__ import annotations

import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def install_bearer_auth(app: FastAPI, token: str | None) -> None:
    """Protect product API paths when a deployment token is configured."""

    @app.middleware("http")
    async def product_auth(request: Request, call_next):
        if token is None or not request.url.path.startswith(("/api/", "/internal/")):
            return await call_next(request)
        authorization = request.headers.get("Authorization", "")
        candidate = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not candidate or not hmac.compare_digest(candidate, token):
            return JSONResponse(status_code=401, content={"detail": "valid product token required"})
        request.state.product_principal = "authenticated"
        return await call_next(request)
