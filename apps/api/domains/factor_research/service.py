from __future__ import annotations

from core.data_feed.factory import get_data_source
from core.data_feed.quality import assess_ohlcv
from core.factor_research import InsufficientFactorData, ResearchConfig, analyze_factors

from .schemas import FactorResearchRequest


def _periods_per_year(market: str, interval: str) -> int:
    normalized = interval.lower()
    if market == "crypto":
        return {"1h": 8_760, "4h": 2_190, "1d": 365}.get(normalized, 365)
    if market == "mt5":
        return {"1h": 6_240, "4h": 1_560, "1d": 252}.get(normalized, 252)
    return {"1h": 1_512, "4h": 378, "1d": 252, "1w": 52}.get(normalized, 252)


def run_factor_research(req: FactorResearchRequest) -> dict:
    try:
        source = get_data_source(req.market)
        frame = source.get_kline(req.symbol, req.interval, limit=req.limit)
    except Exception as exc:  # noqa: BLE001 - adapters may raise third-party transport errors
        return {"ok": False, "error": f"获取 K 线失败: {exc}"}
    quality = assess_ohlcv(frame)
    if not quality.usable:
        return {
            "ok": False,
            "error": f"K线质量不合格: {quality.reason or quality.status}",
            "quality": quality.to_dict(),
        }
    try:
        result = analyze_factors(
            frame,
            ResearchConfig(
                horizon=req.horizon,
                periods_per_year=_periods_per_year(req.market, req.interval),
                transaction_cost_bps=req.transaction_cost_bps,
            ),
        )
    except InsufficientFactorData as exc:
        return {"ok": False, "error": str(exc), "quality": quality.to_dict()}
    return {
        "ok": True,
        "symbol": req.symbol,
        "market": req.market,
        "interval": req.interval,
        "source": frame.attrs.get("_source", getattr(source, "name", "unknown")),
        "quality": quality.to_dict(),
        **result,
    }
