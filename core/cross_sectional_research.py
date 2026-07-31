"""Point-in-time cross-sectional factor research.

The engine consumes historical universe membership and per-symbol OHLCV frames. It
never infers membership from the symbols that happen to have data, which keeps failed,
delisted, suspended and ST constituents visible in coverage statistics.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core.factor_research import (
    FACTOR_FORMULA_VERSION,
    FACTOR_FORMULAS,
    FACTOR_META,
    _clean_frame,
    _factor_series,
)

CROSS_SECTION_ENGINE_VERSION = "1.0.0"


class InsufficientCrossSectionData(ValueError):
    pass


@dataclass(frozen=True)
class CrossSectionConfig:
    market: str = "a_shares"
    factor_key: str = "trend_strength"
    horizon: int = 5
    quantiles: int = 5
    min_assets: int = 5
    periods_per_year: int = 252
    transaction_cost_bps: float = 10.0
    participation_rate: float = 0.1
    neutralize_industry: bool = True
    neutralize_market_cap: bool = True
    neutralize_beta: bool = True


def build_factor_panel(
    frames: dict[str, pd.DataFrame],
    *,
    factor_key: str,
    horizon: int,
) -> pd.DataFrame:
    if factor_key not in FACTOR_META:
        raise ValueError(f"未知因子: {factor_key}")
    parts: list[pd.DataFrame] = []
    for symbol, frame in frames.items():
        data = _clean_frame(frame)
        if "datetime" not in data.columns:
            raise ValueError(f"{symbol} 缺少 datetime 字段")
        factor = _factor_series(data)[factor_key]
        close = data["close"]
        volume = data.get("volume", pd.Series(np.nan, index=data.index))
        parts.append(
            pd.DataFrame(
                {
                    "datetime": pd.to_datetime(data["datetime"], errors="coerce"),
                    "symbol": symbol,
                    "factor": factor,
                    "forward_return": close.shift(-horizon).div(close).sub(1),
                    "dollar_volume": close.mul(volume),
                }
            )
        )
    if not parts:
        return pd.DataFrame(
            columns=["datetime", "symbol", "factor", "forward_return", "dollar_volume"]
        )
    return pd.concat(parts, ignore_index=True).dropna(subset=["datetime"])


def _member_on(
    records: dict[str, list[dict[str, Any]]], symbol: str, timestamp: pd.Timestamp
) -> dict[str, Any] | None:
    day = timestamp.date().isoformat()
    for member in records.get(symbol, []):
        if member["effective_from"] > day:
            continue
        if member.get("effective_to") and member["effective_to"] < day:
            continue
        if member.get("listed_at") and member["listed_at"] > day:
            continue
        if member.get("delisted_at") and member["delisted_at"] < day:
            continue
        if member.get("status") != "active" or member.get("is_st"):
            continue
        return member
    return None


def _neutralize(rows: pd.DataFrame, config: CrossSectionConfig) -> pd.Series | None:
    values = rows["factor"].astype(float)
    exposures: list[pd.Series | pd.DataFrame] = []
    if config.neutralize_industry:
        if rows["industry"].eq("").any():
            return None
        industries = pd.get_dummies(rows["industry"], dtype=float, drop_first=True)
        if not industries.empty:
            exposures.append(industries)
    if config.neutralize_market_cap:
        market_cap = pd.to_numeric(rows["market_cap"], errors="coerce")
        if market_cap.isna().any() or market_cap.le(0).any():
            return None
        exposures.append(np.log(market_cap).rename("log_market_cap"))
    if config.neutralize_beta:
        beta = pd.to_numeric(rows["beta"], errors="coerce")
        if beta.isna().any():
            return None
        exposures.append(beta.rename("beta"))
    if not exposures:
        return values
    design = pd.concat(exposures, axis=1)
    design.insert(0, "intercept", 1.0)
    if len(rows) <= design.shape[1]:
        return None
    coefficients, *_ = np.linalg.lstsq(
        design.to_numpy(dtype=float), values.to_numpy(dtype=float), rcond=None
    )
    return pd.Series(
        values.to_numpy(dtype=float) - design.to_numpy(dtype=float).dot(coefficients),
        index=rows.index,
    )


def _set_turnover(current: set[str], previous: set[str]) -> float:
    if not current and not previous:
        return 0.0
    denominator = max(len(current), len(previous), 1)
    return 1 - len(current & previous) / denominator


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def analyze_cross_sectional_panel(
    panel: pd.DataFrame,
    members: list[dict[str, Any]],
    config: CrossSectionConfig,
) -> dict[str, Any]:
    if panel.empty:
        raise InsufficientCrossSectionData("横截面因子面板为空")
    records: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        records.setdefault(str(member["symbol"]), []).append(member)
    for symbol_records in records.values():
        symbol_records.sort(key=lambda item: item["effective_from"])

    dates = sorted(pd.Timestamp(value) for value in panel["datetime"].dropna().unique())
    date_rows: list[dict[str, Any]] = []
    quantile_returns: dict[int, list[float]] = {
        number: [] for number in range(1, config.quantiles + 1)
    }
    previous_long: set[str] = set()
    previous_short: set[str] = set()
    total_eligible = 0
    total_valid = 0
    neutralization_failures = 0

    for timestamp in dates:
        active_members = {
            symbol: member
            for symbol in records
            if (member := _member_on(records, symbol, timestamp)) is not None
        }
        total_eligible += len(active_members)
        current = panel.loc[panel["datetime"].eq(timestamp)].copy()
        current = current.loc[current["symbol"].isin(active_members)]
        current = current.dropna(subset=["factor", "forward_return"])
        total_valid += len(current)
        if len(current) < config.min_assets:
            continue
        current["industry"] = current["symbol"].map(
            {symbol: item.get("industry", "") for symbol, item in active_members.items()}
        )
        current["market_cap"] = current["symbol"].map(
            {symbol: item.get("market_cap") for symbol, item in active_members.items()}
        )
        current["beta"] = current["symbol"].map(
            {symbol: item.get("beta") for symbol, item in active_members.items()}
        )
        neutral_factor = _neutralize(current, config)
        if neutral_factor is None:
            neutralization_failures += 1
            continue
        current["neutral_factor"] = neutral_factor
        rank_ic = (
            current["neutral_factor"]
            .rank(method="average")
            .corr(current["forward_return"].rank(method="average"))
        )
        if pd.isna(rank_ic):
            continue
        count = min(config.quantiles, len(current))
        current["quantile"] = (
            pd.qcut(
                current["neutral_factor"].rank(method="first"),
                q=count,
                labels=False,
            ).astype(int)
            + 1
        )
        group_returns = current.groupby("quantile")["forward_return"].mean().to_dict()
        for number in range(1, config.quantiles + 1):
            quantile_returns[number].append(float(group_returns.get(number, np.nan)))
        bottom = current.loc[current["quantile"].eq(1)]
        top = current.loc[current["quantile"].eq(count)]
        long_symbols = set(top["symbol"].astype(str))
        short_symbols = set(bottom["symbol"].astype(str))
        turnover = (
            _set_turnover(long_symbols, previous_long)
            + _set_turnover(short_symbols, previous_short)
        ) / 2
        previous_long, previous_short = long_symbols, short_symbols
        raw_long_short = float(top["forward_return"].mean() - bottom["forward_return"].mean())
        net_long_short = raw_long_short - turnover * config.transaction_cost_bps / 10_000
        available_liquidity = pd.to_numeric(top["dollar_volume"], errors="coerce").dropna()
        capacity = float(available_liquidity.sum() * config.participation_rate)
        if available_liquidity.gt(0).any():
            weights = available_liquidity.div(available_liquidity.sum())
            crowding = float(weights.pow(2).sum())
        else:
            crowding = math.nan
        date_rows.append(
            {
                "date": timestamp.isoformat(),
                "eligible_assets": len(active_members),
                "valid_assets": len(current),
                "coverage": round(len(current) / len(active_members), 6) if active_members else 0.0,
                "rank_ic": float(rank_ic),
                "long_short_return": raw_long_short,
                "net_long_short_return": net_long_short,
                "turnover": turnover,
                "capacity": capacity,
                "crowding_hhi": crowding,
                "long_symbols": sorted(long_symbols),
                "short_symbols": sorted(short_symbols),
            }
        )

    if not date_rows:
        raise InsufficientCrossSectionData("没有日期同时满足最小标的数与中性化字段完整性要求")
    rank_ics = pd.Series([row["rank_ic"] for row in date_rows], dtype=float)
    ic_std = float(rank_ics.std(ddof=1)) if len(rank_ics) > 1 else 0.0
    icir = float(rank_ics.mean() / ic_std * math.sqrt(config.periods_per_year)) if ic_std else 0.0
    net_returns = pd.Series([row["net_long_short_return"] for row in date_rows], dtype=float)
    cumulative = float((1 + net_returns).prod() - 1)
    average_ic = float(rank_ics.mean())
    positive_ratio = float(rank_ics.gt(0).mean())
    status = (
        "usable"
        if len(date_rows) >= 20 and average_ic >= 0.03 and positive_ratio >= 0.6
        else "reject"
        if average_ic <= 0
        else "watch"
    )
    compact_panel = [
        {
            "datetime": pd.Timestamp(row.datetime).isoformat(),
            "symbol": str(row.symbol),
            "factor": None if pd.isna(row.factor) else float(row.factor),
            "forward_return": None if pd.isna(row.forward_return) else float(row.forward_return),
        }
        for row in panel.itertuples(index=False)
    ]
    label, category, description = FACTOR_META[config.factor_key]
    return {
        "engine_version": CROSS_SECTION_ENGINE_VERSION,
        "factor": {
            "key": config.factor_key,
            "label": label,
            "category": category,
            "description": description,
            "formula": FACTOR_FORMULAS[config.factor_key],
            "formula_version": FACTOR_FORMULA_VERSION,
            "status": status,
        },
        "summary": {
            "dates": len(date_rows),
            "rank_ic_mean": round(average_ic, 6),
            "rank_ic_median": round(float(rank_ics.median()), 6),
            "rank_ic_std": round(ic_std, 6),
            "icir": round(icir, 6),
            "positive_rank_ic_ratio": round(positive_ratio, 6),
            "long_short_total_return": round(cumulative, 6),
            "coverage": round(total_valid / total_eligible, 6) if total_eligible else 0.0,
            "missing_rate": round(1 - total_valid / total_eligible, 6) if total_eligible else 1.0,
            "average_turnover": round(float(np.mean([row["turnover"] for row in date_rows])), 6),
            "median_capacity": round(float(np.median([row["capacity"] for row in date_rows])), 2),
            "median_crowding_hhi": round(
                float(np.nanmedian([row["crowding_hhi"] for row in date_rows])), 6
            ),
            "neutralization_failures": neutralization_failures,
            "minimum_valid_assets": min(row["valid_assets"] for row in date_rows),
            "median_valid_assets": round(
                float(np.median([row["valid_assets"] for row in date_rows])), 2
            ),
            "data_fingerprint": _fingerprint(compact_panel),
        },
        "quantile_returns": [
            {
                "quantile": number,
                "mean_forward_return": round(float(pd.Series(values).mean()), 6),
            }
            for number, values in quantile_returns.items()
        ],
        "series": [
            {
                **row,
                "rank_ic": round(row["rank_ic"], 6),
                "long_short_return": round(row["long_short_return"], 6),
                "net_long_short_return": round(row["net_long_short_return"], 6),
                "turnover": round(row["turnover"], 6),
                "capacity": round(row["capacity"], 2),
                "crowding_hhi": None
                if math.isnan(row["crowding_hhi"])
                else round(row["crowding_hhi"], 6),
            }
            for row in date_rows
        ],
        "methodology": {
            "market": config.market,
            "periods_per_year": config.periods_per_year,
            "rank_ic": "每个日期对中性化因子值与未来收益分别排序后计算 Pearson 相关系数",
            "icir": "日 Rank IC 均值 / 日 Rank IC 样本标准差 × 年化周期平方根",
            "turnover": "多头与空头等权标的集合单边替换率的平均值",
            "capacity": "最高分层 close × volume 名义值合计 × participation_rate；单位沿用行情源 volume 口径",
            "crowding": "最高分层按成交额权重计算的 Herfindahl-Hirschman Index",
            "neutralization": {
                "industry": config.neutralize_industry,
                "market_cap": config.neutralize_market_cap,
                "beta": config.neutralize_beta,
            },
        },
    }


def analyze_cross_sectional_factors(
    frames: dict[str, pd.DataFrame],
    members: list[dict[str, Any]],
    config: CrossSectionConfig,
) -> dict[str, Any]:
    panel = build_factor_panel(
        frames,
        factor_key=config.factor_key,
        horizon=config.horizon,
    )
    return analyze_cross_sectional_panel(panel, members, config)
