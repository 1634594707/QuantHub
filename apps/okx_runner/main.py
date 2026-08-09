from __future__ import annotations

from fastapi import FastAPI, HTTPException

from packages.product_auth import install_bearer_auth

from .adapter import DisabledAdapter, TradingAdapter
from .config import RunnerSettings, load_settings
from .database import initialize
from .engine import RunnerEngine
from .okx_adapter import create_okx_adapter_from_env
from .schemas import OrderRequest, PackageImport, RiskModeRequest


def create_app(
    settings: RunnerSettings | None = None, adapter: TradingAdapter | None = None
) -> FastAPI:
    settings = settings or load_settings()
    selected_adapter = adapter
    if selected_adapter is None:
        selected_adapter = (
            DisabledAdapter()
            if settings.environment == "shadow"
            else create_okx_adapter_from_env(settings.environment)
        )
    engine = RunnerEngine(
        settings.database_path,
        selected_adapter,
        settings.signing_key,
        settings.environment,
        settings.version,
    )
    product = FastAPI(title="QuantHub OKX Runner", version=settings.version)
    product.state.settings = settings
    product.state.engine = engine
    install_bearer_auth(product, settings.auth_token)

    @product.get("/health")
    def health() -> dict:
        initialize(settings.database_path)
        return {
            "status": "ok",
            "product": "okx_runner",
            "version": settings.version,
            "environment": settings.environment,
            "database": str(settings.database_path),
            "formula_editing": False,
            "ai_parameter_updates": False,
        }

    @product.post("/api/strategies/import")
    def import_strategy(request: PackageImport) -> dict:
        return _call(engine.import_package, request.package)

    @product.get("/api/dashboard")
    def dashboard() -> dict:
        return engine.dashboard()

    @product.get("/api/strategies/{strategy_id}/{version}")
    def strategy(strategy_id: str, version: str) -> dict:
        return _call(engine.strategy, strategy_id, version)

    @product.get("/api/accounts/{account_id}")
    def account(account_id: str) -> dict:
        return _call(engine.account, account_id)

    @product.post("/api/orders")
    def submit_order(request: OrderRequest) -> dict:
        return _call(engine.submit, request)

    @product.get("/api/orders/{order_id}")
    def get_order(order_id: str) -> dict:
        return _call(engine.order, order_id)

    @product.post("/api/orders/{order_id}/cancel")
    def cancel_order(order_id: str) -> dict:
        return _call(engine.cancel, order_id)

    @product.post("/api/recovery/orders")
    def recover_orders() -> list[dict]:
        return _call(engine.recover_open_orders)

    @product.post("/api/reconciliation/{account_id}")
    def reconcile(account_id: str) -> dict:
        return _call(engine.reconcile, account_id)

    @product.get("/api/reconciliation/diffs/{diff_id}")
    def reconciliation_diff(diff_id: str) -> dict:
        return _call(engine.reconciliation_diff, diff_id)

    @product.post("/api/reconciliation/diffs/{diff_id}/resolve")
    def resolve_diff(diff_id: str, payload: dict) -> dict:
        return _call(
            engine.resolve_diff,
            diff_id,
            str(payload.get("owner", "")),
            str(payload.get("resolution", "")),
        )

    @product.post("/api/risk/mode")
    def risk_mode(request: RiskModeRequest) -> dict:
        return _call(
            engine.set_risk_mode,
            request.scope,
            request.mode,
            request.reason,
            request.operator,
        )

    @product.post("/api/replay/{strategy_id}/{version}")
    def replay(strategy_id: str, version: str, bars: list[dict]) -> dict:
        return _call(engine.deterministic_replay, strategy_id, version, bars)

    @product.post("/api/shadow/{strategy_id}/{version}")
    def shadow(
        strategy_id: str, version: str, bars: list[dict], feed_mode: str = "external"
    ) -> dict:
        return _call(engine.run_shadow_session, strategy_id, version, bars, feed_mode=feed_mode)

    @product.post("/api/runtime-results/{strategy_id}/{version}")
    def runtime_result(strategy_id: str, version: str, result: dict) -> dict:
        return _call(engine.record_runtime_result, strategy_id, version, result)

    return product


def _call(function, *args):
    try:
        return function(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


app = create_app()


def run() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run("apps.okx_runner.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    run()
