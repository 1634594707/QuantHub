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
from typing import Any, Literal

import numpy as np
import pandas as pd

from core.factor_research import (
    FACTOR_FORMULA_VERSION,
    FACTOR_FORMULAS,
    FACTOR_META,
    _clean_frame,
    _factor_series,
)

CROSS_SECTION_ENGINE_VERSION = "2.2.0"
LABEL_HORIZONS = (1, 3, 5, 10, 20)

MARKET_VALIDATION_THRESHOLDS = {
    "a_shares": {"minimum_effective_dates": 120, "minimum_valid_assets": 30},
    "us_stocks": {"minimum_effective_dates": 120, "minimum_valid_assets": 30},
    "crypto": {"minimum_effective_dates": 180, "minimum_valid_assets": 20},
    "mt5": {"minimum_effective_dates": 120, "minimum_valid_assets": 20},
}


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
    portfolio_mode: Literal["cohort", "non_overlapping"] = "cohort"
    minimum_effective_dates: int | None = None
    minimum_valid_assets: int | None = None


def validation_thresholds(config: CrossSectionConfig) -> dict[str, int]:
    defaults = MARKET_VALIDATION_THRESHOLDS.get(
        config.market,
        {"minimum_effective_dates": 120, "minimum_valid_assets": 20},
    )
    return {
        "minimum_effective_dates": (
            config.minimum_effective_dates
            if config.minimum_effective_dates is not None
            else defaults["minimum_effective_dates"]
        ),
        "minimum_valid_assets": (
            config.minimum_valid_assets
            if config.minimum_valid_assets is not None
            else defaults["minimum_valid_assets"]
        ),
    }


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
        daily_volatility = close.pct_change().rolling(20, min_periods=10).std(ddof=0)
        labels: dict[str, pd.Series] = {}
        for label_horizon in LABEL_HORIZONS:
            forward = close.shift(-label_horizon).div(close).sub(1)
            labels[f"forward_return_{label_horizon}"] = forward
            labels[f"risk_adjusted_return_{label_horizon}"] = forward.div(
                daily_volatility.mul(math.sqrt(label_horizon)).replace(0, np.nan)
            )
        parts.append(
            pd.DataFrame(
                {
                    "datetime": pd.to_datetime(data["datetime"], errors="coerce"),
                    "symbol": symbol,
                    "factor": factor,
                    "forward_return": close.shift(-horizon).div(close).sub(1),
                    "next_return": close.shift(-1).div(close).sub(1),
                    "dollar_volume": close.mul(volume),
                    **labels,
                }
            )
        )
    if not parts:
        return pd.DataFrame(
            columns=[
                "datetime",
                "symbol",
                "factor",
                "forward_return",
                "next_return",
                "dollar_volume",
                *[
                    f"{prefix}_{label_horizon}"
                    for prefix in ("forward_return", "risk_adjusted_return")
                    for label_horizon in LABEL_HORIZONS
                ],
            ]
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


def _residualize_column(
    rows: pd.DataFrame,
    column: str,
    config: CrossSectionConfig,
    *,
    always_intercept: bool = False,
) -> pd.Series | None:
    values = rows[column].astype(float)
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
    if not exposures and not always_intercept:
        return values
    design = pd.concat(exposures, axis=1) if exposures else pd.DataFrame(index=rows.index)
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


def _neutralize(rows: pd.DataFrame, config: CrossSectionConfig) -> pd.Series | None:
    return _residualize_column(rows, "factor", config)


def _rank_ic(left: pd.Series, right: pd.Series) -> float | None:
    pair = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 3 or pair.iloc[:, 0].nunique() < 2 or pair.iloc[:, 1].nunique() < 2:
        return None
    value = pair.iloc[:, 0].rank(method="average").corr(pair.iloc[:, 1].rank(method="average"))
    return None if pd.isna(value) else float(value)


def _stability_rows(
    values: dict[str, list[float]], primary_direction: float
) -> list[dict[str, Any]]:
    rows = []
    for key, observations in sorted(values.items()):
        clean = pd.Series(observations, dtype=float).dropna()
        if clean.empty:
            continue
        mean = float(clean.mean())
        rows.append(
            {
                "segment": key,
                "observations": len(clean),
                "rank_ic_mean": round(mean, 6),
                "positive_ratio": round(float(clean.gt(0).mean()), 6),
                "direction_consistent": mean * primary_direction >= 0,
            }
        )
    return rows


def _equal_weights(symbols: set[str]) -> dict[str, float]:
    if not symbols:
        return {}
    weight = 1 / len(symbols)
    return {symbol: weight for symbol in symbols}


def _average_cohort_weights(
    cohorts: list[dict[str, Any]],
    side: str,
) -> dict[str, float]:
    if not cohorts:
        return {}
    combined: dict[str, float] = {}
    cohort_weight = 1 / len(cohorts)
    for cohort in cohorts:
        for symbol, weight in cohort[side].items():
            combined[symbol] = combined.get(symbol, 0.0) + cohort_weight * float(weight)
    return combined


def _weight_turnover(current: dict[str, float], previous: dict[str, float]) -> float:
    symbols = set(current) | set(previous)
    purchases = sum(
        max(current.get(symbol, 0.0) - previous.get(symbol, 0.0), 0.0) for symbol in symbols
    )
    sales = sum(
        max(previous.get(symbol, 0.0) - current.get(symbol, 0.0), 0.0) for symbol in symbols
    )
    return max(purchases, sales)


def _weighted_return(weights: dict[str, float], returns: dict[str, float]) -> float:
    return float(sum(weight * returns.get(symbol, 0.0) for symbol, weight in weights.items()))


def _newey_west_mean_test(values: pd.Series, max_lag: int) -> tuple[float, int, int]:
    clean = pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    observations = len(clean)
    if observations < 3:
        return 1.0, observations, 0
    centered = clean.to_numpy(dtype=float) - float(clean.mean())
    gamma_zero = float(np.dot(centered, centered) / observations)
    lag_count = min(max(int(max_lag), 0), observations - 1)
    long_run_variance = gamma_zero
    for lag in range(1, lag_count + 1):
        weight = 1 - lag / (lag_count + 1)
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / observations)
        long_run_variance += 2 * weight * covariance
    long_run_variance = max(long_run_variance, 0.0)
    mean = float(clean.mean())
    if long_run_variance <= 1e-20:
        return (0.0 if abs(mean) > 1e-12 else 1.0), observations, lag_count
    standard_error = math.sqrt(long_run_variance / observations)
    statistic = abs(mean) / standard_error
    p_value = math.erfc(statistic / math.sqrt(2))
    effective_observations = int(
        round(min(max(observations * gamma_zero / long_run_variance, 3), observations))
    )
    return min(max(p_value, 0.0), 1.0), effective_observations, lag_count


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
    if config.horizon < 1:
        raise ValueError("horizon 必须大于等于 1")
    if config.portfolio_mode not in {"cohort", "non_overlapping"}:
        raise ValueError("portfolio_mode 必须为 cohort 或 non_overlapping")
    if config.portfolio_mode == "cohort" and "next_return" not in panel.columns:
        raise ValueError("cohort 组合需要 next_return 字段")
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
    previous_long_weights: dict[str, float] = {}
    previous_short_weights: dict[str, float] = {}
    previous_benchmark_weights: dict[str, float] = {}
    active_cohorts: list[dict[str, Any]] = []
    total_eligible = 0
    total_valid = 0
    neutralization_failures = 0
    raw_rank_ic_values: list[float] = []
    label_stability_values: dict[str, list[float]] = {}
    cross_section_stability_values: dict[str, dict[str, list[float]]] = {
        "industry": {},
        "market_cap": {},
        "liquidity": {},
        "listing_age": {},
    }

    for timestamp in dates:
        active_members = {
            symbol: member
            for symbol in records
            if (member := _member_on(records, symbol, timestamp)) is not None
        }
        total_eligible += len(active_members)
        date_panel = panel.loc[panel["datetime"].eq(timestamp)].copy()
        next_returns = {
            str(row.symbol): float(row.next_return)
            for row in date_panel.itertuples(index=False)
            if hasattr(row, "next_return") and pd.notna(row.next_return)
        }
        current = date_panel.copy()
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
        current["listed_at"] = current["symbol"].map(
            {symbol: item.get("listed_at") for symbol, item in active_members.items()}
        )
        neutral_factor = _neutralize(current, config)
        residual_return = _residualize_column(
            current,
            "forward_return",
            config,
            always_intercept=True,
        )
        if neutral_factor is None or residual_return is None:
            neutralization_failures += 1
            continue
        current["neutral_factor"] = neutral_factor
        current["residual_forward_return"] = residual_return
        rank_ic = _rank_ic(current["neutral_factor"], current["residual_forward_return"])
        raw_rank_ic = _rank_ic(current["neutral_factor"], current["forward_return"])
        if rank_ic is None:
            continue
        if raw_rank_ic is not None:
            raw_rank_ic_values.append(raw_rank_ic)

        primary_label_key = f"residual_forward_return_{config.horizon}"
        label_stability_values.setdefault(primary_label_key, []).append(rank_ic)
        date_label_ics: dict[str, float] = {primary_label_key: rank_ic}
        for label_horizon in LABEL_HORIZONS:
            for prefix in ("forward_return", "risk_adjusted_return"):
                column = f"{prefix}_{label_horizon}"
                if prefix == "forward_return" and label_horizon == config.horizon:
                    continue
                if column not in current:
                    continue
                eligible_label_rows = current.dropna(subset=[column]).copy()
                if len(eligible_label_rows) < 3:
                    continue
                residual_label = _residualize_column(
                    eligible_label_rows,
                    column,
                    config,
                    always_intercept=True,
                )
                if residual_label is None:
                    continue
                label_ic = _rank_ic(
                    eligible_label_rows["neutral_factor"],
                    residual_label,
                )
                if label_ic is None:
                    continue
                label_key = f"residual_{prefix}_{label_horizon}"
                label_stability_values.setdefault(label_key, []).append(label_ic)
                date_label_ics[label_key] = label_ic

        subgroup_sources: dict[str, pd.Series] = {
            "industry": current["industry"].astype(str),
            "listing_age": pd.cut(
                (timestamp - pd.to_datetime(current["listed_at"], errors="coerce")).dt.days,
                bins=[-np.inf, 365, 365 * 3, np.inf],
                labels=["under_1y", "1_to_3y", "over_3y"],
            ).astype(str),
        }
        for dimension, column in (("market_cap", "market_cap"), ("liquidity", "dollar_volume")):
            numeric = pd.to_numeric(current[column], errors="coerce")
            try:
                subgroup_sources[dimension] = pd.qcut(
                    numeric.rank(method="first"),
                    q=min(3, int(numeric.notna().sum())),
                    labels=["low", "mid", "high"][: min(3, int(numeric.notna().sum()))],
                ).astype(str)
            except ValueError:
                subgroup_sources[dimension] = pd.Series("all", index=current.index)
        for dimension, groups in subgroup_sources.items():
            for group in sorted(groups.dropna().unique()):
                group_mask = groups.eq(group)
                if int(group_mask.sum()) < 3:
                    continue
                group_ic = _rank_ic(
                    current.loc[group_mask, "neutral_factor"],
                    current.loc[group_mask, "residual_forward_return"],
                )
                if group_ic is not None:
                    cross_section_stability_values[dimension].setdefault(str(group), []).append(
                        group_ic
                    )
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
        raw_long_short = float(top["forward_return"].mean() - bottom["forward_return"].mean())
        formation_index = len(date_rows)
        new_long_weights = _equal_weights(long_symbols)
        new_short_weights = _equal_weights(short_symbols)
        new_benchmark_weights = _equal_weights(set(current["symbol"].astype(str)))
        portfolio_gross_return: float | None
        portfolio_net_return: float | None
        long_only_net_return: float | None
        long_only_excess_return: float | None
        benchmark_return: float | None
        portfolio_long_weights: dict[str, float]
        portfolio_short_weights: dict[str, float]
        portfolio_benchmark_weights: dict[str, float]
        active_cohort_count: int
        if config.portfolio_mode == "cohort":
            active_cohorts = [
                cohort
                for cohort in active_cohorts
                if formation_index - int(cohort["formation_index"]) < config.horizon
            ]
            active_cohorts.append(
                {
                    "formation_index": formation_index,
                    "long": new_long_weights,
                    "short": new_short_weights,
                    "benchmark": new_benchmark_weights,
                }
            )
            portfolio_long_weights = _average_cohort_weights(active_cohorts, "long")
            portfolio_short_weights = _average_cohort_weights(active_cohorts, "short")
            portfolio_benchmark_weights = _average_cohort_weights(active_cohorts, "benchmark")
            long_gross_return = _weighted_return(portfolio_long_weights, next_returns)
            short_gross_return = _weighted_return(portfolio_short_weights, next_returns)
            benchmark_return = _weighted_return(portfolio_benchmark_weights, next_returns)
            portfolio_gross_return = long_gross_return - short_gross_return
            active_cohort_count = len(active_cohorts)
        elif formation_index % config.horizon == 0:
            portfolio_long_weights = new_long_weights
            portfolio_short_weights = new_short_weights
            portfolio_benchmark_weights = new_benchmark_weights
            long_gross_return = float(top["forward_return"].mean())
            short_gross_return = float(bottom["forward_return"].mean())
            benchmark_return = float(current["forward_return"].mean())
            portfolio_gross_return = raw_long_short
            active_cohort_count = 1
        else:
            portfolio_long_weights = previous_long_weights
            portfolio_short_weights = previous_short_weights
            portfolio_benchmark_weights = previous_benchmark_weights
            long_gross_return = None
            benchmark_return = None
            portfolio_gross_return = None
            active_cohort_count = 1 if portfolio_long_weights or portfolio_short_weights else 0
        if portfolio_gross_return is None:
            turnover = 0.0
            long_turnover = 0.0
            portfolio_net_return = None
            long_only_net_return = None
            long_only_excess_return = None
        else:
            long_turnover = _weight_turnover(portfolio_long_weights, previous_long_weights)
            short_turnover = _weight_turnover(portfolio_short_weights, previous_short_weights)
            turnover = (long_turnover + short_turnover) / 2
            portfolio_net_return = portfolio_gross_return - (
                turnover * config.transaction_cost_bps / 10_000
            )
            long_only_net_return = float(long_gross_return) - (
                long_turnover * config.transaction_cost_bps / 10_000
            )
            long_only_excess_return = long_only_net_return - float(benchmark_return)
            previous_long_weights = portfolio_long_weights
            previous_short_weights = portfolio_short_weights
            previous_benchmark_weights = portfolio_benchmark_weights
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
                "raw_return_rank_ic": raw_rank_ic,
                "label_rank_ics": date_label_ics,
                "long_short_return": raw_long_short,
                "net_long_short_return": portfolio_net_return,
                "portfolio_gross_return": portfolio_gross_return,
                "portfolio_net_return": portfolio_net_return,
                "long_only_net_return": long_only_net_return,
                "benchmark_return": benchmark_return,
                "long_only_excess_return": long_only_excess_return,
                "portfolio_active_cohorts": active_cohort_count,
                "turnover": turnover,
                "long_turnover": long_turnover,
                "capacity": capacity,
                "crowding_hhi": crowding,
                "long_symbols": sorted(long_symbols),
                "short_symbols": sorted(short_symbols),
                "portfolio_long_symbols": sorted(portfolio_long_weights),
                "portfolio_short_symbols": sorted(portfolio_short_weights),
                "portfolio_benchmark_symbols": sorted(portfolio_benchmark_weights),
            }
        )

    if not date_rows:
        raise InsufficientCrossSectionData("没有日期同时满足最小标的数与中性化字段完整性要求")
    rank_ics = pd.Series([row["rank_ic"] for row in date_rows], dtype=float)
    rank_ic_p_value, effective_dates, rank_ic_hac_lags = _newey_west_mean_test(
        rank_ics,
        max(config.horizon - 1, 0),
    )
    ic_std = float(rank_ics.std(ddof=1)) if len(rank_ics) > 1 else 0.0
    icir = (
        float(rank_ics.mean() / ic_std * math.sqrt(config.periods_per_year))
        if ic_std
        else 99.0
        if float(rank_ics.mean()) > 0
        else -99.0
        if float(rank_ics.mean()) < 0
        else 0.0
    )
    gross_returns = pd.Series(
        [row["portfolio_gross_return"] for row in date_rows], dtype=float
    ).dropna()
    net_returns = pd.Series(
        [row["portfolio_net_return"] for row in date_rows], dtype=float
    ).dropna()
    long_only_returns = pd.Series(
        [row["long_only_net_return"] for row in date_rows], dtype=float
    ).dropna()
    benchmark_returns = pd.Series(
        [row["benchmark_return"] for row in date_rows], dtype=float
    ).dropna()
    long_only_excess_returns = pd.Series(
        [row["long_only_excess_return"] for row in date_rows], dtype=float
    ).dropna()
    gross_cumulative = float((1 + gross_returns).prod() - 1)
    net_cumulative = float((1 + net_returns).prod() - 1)
    long_only_cumulative = float((1 + long_only_returns).prod() - 1)
    benchmark_cumulative = float((1 + benchmark_returns).prod() - 1)
    long_only_excess_cumulative = float((1 + long_only_excess_returns).prod() - 1)
    primary_portfolio_key = (
        "long_only_excess" if config.market == "a_shares" else "theoretical_long_short"
    )
    primary_total_return = (
        long_only_excess_cumulative if config.market == "a_shares" else net_cumulative
    )
    average_ic = float(rank_ics.mean())
    positive_ratio = float(rank_ics.gt(0).mean())
    raw_rank_ic_mean = float(pd.Series(raw_rank_ic_values).mean()) if raw_rank_ic_values else 0.0
    label_stability = _stability_rows(label_stability_values, average_ic)
    cross_section_stability = {
        dimension: _stability_rows(values, average_ic)
        for dimension, values in cross_section_stability_values.items()
    }
    time_stability_values: dict[str, list[float]] = {}
    stability_frame = pd.DataFrame(date_rows)
    stability_frame["timestamp"] = pd.to_datetime(stability_frame["date"], errors="coerce")
    benchmark_series = pd.to_numeric(stability_frame["benchmark_return"], errors="coerce").fillna(
        0.0
    )
    rolling_mean = benchmark_series.rolling(20, min_periods=3).mean().fillna(0.0)
    rolling_volatility = benchmark_series.rolling(20, min_periods=3).std(ddof=0).fillna(0.0)
    volatility_median = float(rolling_volatility.median())
    liquidity_median = float(pd.to_numeric(stability_frame["capacity"]).median())
    for index, row in stability_frame.iterrows():
        row_ic = float(row["rank_ic"])
        year = str(row["timestamp"].year)
        market_direction = "bull" if rolling_mean.iloc[index] >= 0 else "bear"
        trend_state = (
            "trend"
            if abs(float(rolling_mean.iloc[index]))
            > max(float(rolling_volatility.iloc[index]) * 0.25, 1e-12)
            else "range"
        )
        volatility_state = (
            "high_volatility"
            if float(rolling_volatility.iloc[index]) >= volatility_median
            else "low_volatility"
        )
        liquidity_state = (
            "high_liquidity" if float(row["capacity"]) >= liquidity_median else "low_liquidity"
        )
        for segment in (
            f"year:{year}",
            f"market:{market_direction}",
            f"trend:{trend_state}",
            f"volatility:{volatility_state}",
            f"liquidity:{liquidity_state}",
        ):
            time_stability_values.setdefault(segment, []).append(row_ic)
    time_stability = _stability_rows(time_stability_values, average_ic)
    minimum_valid_assets = min(row["valid_assets"] for row in date_rows)
    thresholds = validation_thresholds(config)
    status = (
        "usable"
        if effective_dates >= thresholds["minimum_effective_dates"]
        and minimum_valid_assets >= thresholds["minimum_valid_assets"]
        and average_ic >= 0.03
        and positive_ratio >= 0.6
        and rank_ic_p_value <= 0.05
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
            "next_return": (
                None
                if not hasattr(row, "next_return") or pd.isna(row.next_return)
                else float(row.next_return)
            ),
            "label_horizons": {
                column: None if pd.isna(getattr(row, column)) else float(getattr(row, column))
                for column in (
                    f"{prefix}_{label_horizon}"
                    for prefix in ("forward_return", "risk_adjusted_return")
                    for label_horizon in LABEL_HORIZONS
                )
                if hasattr(row, column)
            },
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
            "raw_return_rank_ic_mean": round(raw_rank_ic_mean, 6),
            "primary_label": "market_industry_neutral_residual_return",
            "auxiliary_label": "raw_forward_return",
            "rank_ic_median": round(float(rank_ics.median()), 6),
            "rank_ic_std": round(ic_std, 6),
            "icir": round(icir, 6),
            "rank_ic_p_value": round(rank_ic_p_value, 6),
            "rank_ic_p_value_method": "newey_west_hac_mean_test",
            "rank_ic_hac_lags": rank_ic_hac_lags,
            "effective_dates": effective_dates,
            "positive_rank_ic_ratio": round(positive_ratio, 6),
            "portfolio_mode": config.portfolio_mode,
            "portfolio_return_horizon": 1 if config.portfolio_mode == "cohort" else config.horizon,
            "portfolio_observations": len(net_returns),
            "gross_long_short_total_return": round(gross_cumulative, 6),
            "net_long_short_total_return": round(net_cumulative, 6),
            "long_short_total_return": round(net_cumulative, 6),
            "long_only_total_return": round(long_only_cumulative, 6),
            "benchmark_total_return": round(benchmark_cumulative, 6),
            "long_only_excess_total_return": round(long_only_excess_cumulative, 6),
            "primary_portfolio_key": primary_portfolio_key,
            "primary_total_return": round(primary_total_return, 6),
            "portfolio_variants": {
                "long_only": {
                    "available": True,
                    "executable": True,
                    "total_return": round(long_only_cumulative, 6),
                },
                "long_only_excess": {
                    "available": True,
                    "executable": True,
                    "benchmark": "equal_weight_eligible_universe",
                    "total_return": round(long_only_excess_cumulative, 6),
                },
                "theoretical_long_short": {
                    "available": True,
                    "executable": config.market != "a_shares",
                    "total_return": round(net_cumulative, 6),
                },
                "index_hedged": {
                    "available": False,
                    "executable": False,
                    "total_return": None,
                    "reason": "尚未提供与研究日期对齐的可交易指数或股指期货基准",
                },
            },
            "coverage": round(total_valid / total_eligible, 6) if total_eligible else 0.0,
            "missing_rate": round(1 - total_valid / total_eligible, 6) if total_eligible else 1.0,
            "average_turnover": round(
                float(
                    np.mean(
                        [
                            row["turnover"]
                            for row in date_rows
                            if row["portfolio_net_return"] is not None
                        ]
                    )
                ),
                6,
            ),
            "average_long_turnover": round(
                float(
                    np.mean(
                        [
                            row["long_turnover"]
                            for row in date_rows
                            if row["long_only_net_return"] is not None
                        ]
                    )
                ),
                6,
            ),
            "median_capacity": round(float(np.median([row["capacity"] for row in date_rows])), 2),
            "median_crowding_hhi": round(
                float(np.nanmedian([row["crowding_hhi"] for row in date_rows])), 6
            ),
            "neutralization_failures": neutralization_failures,
            "minimum_valid_assets": minimum_valid_assets,
            "median_valid_assets": round(
                float(np.median([row["valid_assets"] for row in date_rows])), 2
            ),
            "validation_thresholds": thresholds,
            "data_fingerprint": _fingerprint(compact_panel),
        },
        "quantile_returns": [
            {
                "quantile": number,
                "mean_forward_return": round(float(pd.Series(values).mean()), 6),
            }
            for number, values in quantile_returns.items()
        ],
        "stability": {
            "labels": label_stability,
            "time": time_stability,
            "cross_section": cross_section_stability,
            "regime_definition": {
                "bull_bear": "20 期等权基准收益均值的正负",
                "trend_range": "20 期均值绝对值是否超过同期波动的 25%",
                "volatility": "20 期基准波动相对样本中位数",
                "liquidity": "当期组合容量相对样本中位数",
            },
        },
        "series": [
            {
                **row,
                "rank_ic": round(row["rank_ic"], 6),
                "long_short_return": round(row["long_short_return"], 6),
                "net_long_short_return": None
                if row["net_long_short_return"] is None
                else round(row["net_long_short_return"], 6),
                "portfolio_gross_return": None
                if row["portfolio_gross_return"] is None
                else round(row["portfolio_gross_return"], 6),
                "portfolio_net_return": None
                if row["portfolio_net_return"] is None
                else round(row["portfolio_net_return"], 6),
                "long_only_net_return": None
                if row["long_only_net_return"] is None
                else round(row["long_only_net_return"], 6),
                "benchmark_return": None
                if row["benchmark_return"] is None
                else round(row["benchmark_return"], 6),
                "long_only_excess_return": None
                if row["long_only_excess_return"] is None
                else round(row["long_only_excess_return"], 6),
                "turnover": round(row["turnover"], 6),
                "long_turnover": round(row["long_turnover"], 6),
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
            "primary_label": (
                "主标签为市场截面均值及所配置行业、市值、Beta 暴露中性化后的未来残差收益；"
                "原始未来收益 Rank IC 仅作辅助指标"
            ),
            "icir": "日 Rank IC 均值 / 日 Rank IC 样本标准差 × 年化周期平方根",
            "rank_ic_significance": "Rank IC 时间序列均值执行 Newey-West HAC 双侧检验，滞后覆盖预测窗口重叠",
            "portfolio_mode": config.portfolio_mode,
            "portfolio_return": (
                "每日新建等权多空批次，每个批次持有 horizon 个周期；活跃批次等权合并后使用下一周期收益计账"
                if config.portfolio_mode == "cohort"
                else "每 horizon 个有效日期调仓一次，仅复利互不重叠的 horizon 周期收益"
            ),
            "a_share_execution": (
                "A 股默认以最高分层多头成本后收益减去当期可选股票池等权基准作为主组合；"
                "理论多空只作为研究证据，不标记为可执行"
                if config.market == "a_shares"
                else "目标市场允许时以理论多空作为主要研究组合，实际可执行性仍由市场档案决定"
            ),
            "turnover": "按组合权重变化计算多空两侧单边换手的平均值，只在真实组合计账期扣费",
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
