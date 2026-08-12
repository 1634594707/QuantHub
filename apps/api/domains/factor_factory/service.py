from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

from apps.api import store
from apps.api.domains.factor_research.schemas import (
    FactorAiSearchRoundRequest,
    FactorCandidateValidationRequest,
    FactorConfirmationSetOpenRequest,
    FactorDefinitionCreate,
    FactorExperimentCreate,
    FactorExperimentEventCreate,
    FactorLifecycleTransitionRequest,
    FactorPreRegistration,
    FactorResearchDataPartition,
    FactorResearchDataSplit,
    FactorResearchPlanCreate,
)
from apps.api.domains.factor_research.service import (
    append_factor_experiment_event,
    create_factor_experiment_record,
    create_factor_research_plan_record,
    open_factor_confirmation_set,
    register_factor_definition,
    transition_factor_lifecycle,
    validate_factor_ai_search_round,
    validate_factor_candidate_data,
)
from apps.api.domains.simulation import service as simulation_service
from apps.api.domains.simulation.schemas import SimulationFillCreate, SimulationOrderCreate
from apps.api.domains.trading import errors as trading_errors
from core.backtest import dataset as dataset_module
from core.backtest import market_data as market_data_module
from core.backtest.strategies_demo import run_signal_backtest
from core.factor_dsl import (
    FactorDefinition,
    FactorDslError,
    detect_series_redundancy,
    evaluate_factor_ast,
    validate_factor_definition,
)
from core.factor_monitoring import (
    factor_drift_report,
    research_simulation_gap_attribution,
    simulation_validation_report,
)
from core.factor_research import FACTOR_META
from packages.strategy_package import StrategyReleasePackage

from .alpha_mining import (
    AI_PROMPT_VERSION,
    ALPHA_MINING_VERSION,
    AlphaProposal,
    generate_ai_proposals,
    generate_grammar_proposals,
    parse_alpha_expression,
)
from .okx_demo import (
    activate_demo_strategy,
    build_demo_release_package,
    refresh_demo_evidence,
)
from .schemas import FactorFactoryStartRequest

logger = logging.getLogger(__name__)
_observe_lock = threading.RLock()
_discovery_lock = threading.RLock()
FACTOR_FACTORY_RESEARCH_VERSION = "3.1.1"
ARCHIVE_MINIMUM_OBSERVATION_DAYS = 7
ARCHIVE_MINIMUM_OBSERVATION_SECONDS = ARCHIVE_MINIMUM_OBSERVATION_DAYS * 86_400


@dataclass(frozen=True)
class CandidateSpec:
    key: str
    label: str
    family: str
    source: str
    lookback: int
    ast: dict[str, Any]
    hypothesis: str
    invalidation: str
    falsification_tests: tuple[str, ...] = (
        "rolling_validation_stability",
        "double_cost_stress",
    )
    model: dict[str, Any] = field(default_factory=dict)
    prompt: dict[str, Any] = field(default_factory=dict)
    ai_trace: dict[str, Any] = field(default_factory=dict)


_OPERATOR_FAMILIES = {
    "time_series": {"rolling_mean", "rolling_std", "rolling_min", "rolling_max", "rolling_sum"},
    "normalization": {"rolling_zscore", "rolling_winsorize"},
    "arithmetic": {"add", "sub", "mul", "div", "neg", "abs"},
    "ranking": {"rank", "industry_neutralize"},
    "conditional": {"gt", "lt", "where"},
    "lag_change": {"lag", "diff", "pct_change"},
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    return value


def _ast_operator_families(node: Any) -> set[str]:
    if not isinstance(node, dict):
        return set()
    op = str(node.get("op") or "")
    families = {family for family, operators in _OPERATOR_FAMILIES.items() if op in operators}
    for value in node.values():
        if isinstance(value, dict):
            families.update(_ast_operator_families(value))
        elif isinstance(value, list):
            for item in value:
                families.update(_ast_operator_families(item))
    return families


def _normal_survival(value: float) -> float:
    return 0.5 * math.erfc(value / math.sqrt(2.0))


def _wilson_lower_bound(successes: int, total: int, *, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    center = proportion + z * z / (2 * total)
    margin = z * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
    return max(0.0, (center - margin) / denominator)


def _bimodality_coefficient(values: list[float]) -> float | None:
    count = len(values)
    if count < 4:
        return None
    array = np.asarray(values, dtype=float)
    deviation = array - float(array.mean())
    variance = float(np.mean(deviation**2))
    if variance <= 1e-12:
        return 0.0
    skewness = float(np.mean(deviation**3) / variance**1.5)
    kurtosis = float(np.mean(deviation**4) / variance**2) - 3.0
    denominator = kurtosis + 3 * (count - 1) ** 2 / ((count - 2) * (count - 3))
    if abs(denominator) <= 1e-12:
        return None
    return (skewness * skewness + 1) / denominator


def _mean_signal_probability(values: list[float], *, noise_floor: float) -> tuple[float, str]:
    count = len(values)
    if count == 0:
        return 0.0, "none"
    array = np.asarray(values, dtype=float)
    if count < 8:
        rng = np.random.default_rng(20260812 + count)
        samples = rng.choice(array, size=(2_000, count), replace=True).mean(axis=1)
        return float(np.mean(samples > noise_floor)), "bootstrap"
    standard_deviation = float(array.std(ddof=1))
    if standard_deviation <= 1e-12:
        return (1.0 if float(array.mean()) > noise_floor else 0.0), "normal"
    statistic = (float(array.mean()) - noise_floor) / (standard_deviation / math.sqrt(count))
    return 1.0 - _normal_survival(statistic), "normal"


def _direction_bucket(
    rows: list[dict[str, Any]],
    *,
    name: str,
    noise_floor: float = 1.0,
) -> dict[str, Any]:
    sharpes = [float(row["sharpe"]) for row in rows if row.get("sharpe") is not None]
    returns = [float(row["return"]) for row in rows if row.get("return") is not None]
    pass_count = sum(1 for row in rows if row.get("passed"))
    operator_families = sorted(
        {family for row in rows for family in row.get("operator_families", [])}
    )
    count = len(sharpes)
    mean_sharpe = float(np.mean(sharpes)) if sharpes else 0.0
    maximum_sharpe = max(sharpes, default=0.0)
    standard_deviation = float(np.std(sharpes, ddof=1)) if count > 1 else 0.0
    signal_probability, significance_method = _mean_signal_probability(
        sharpes,
        noise_floor=noise_floor,
    )
    pass_rate = pass_count / len(rows) if rows else 0.0
    pass_rate_lower = _wilson_lower_bound(pass_count, len(rows))
    coefficient_variation = standard_deviation / max(abs(mean_sharpe), 0.25)
    consistency = 1 / (1 + coefficient_variation)
    ceiling_score = min(1.0, max(0.0, maximum_sharpe / 2.0))
    dsi = (
        0.30 * signal_probability
        + 0.25 * ceiling_score
        + 0.25 * pass_rate_lower
        + 0.20 * consistency
    )
    bimodality = _bimodality_coefficient(sharpes)
    bimodal_protection = bool(bimodality is not None and bimodality > 0.556)
    ceiling_protection = maximum_sharpe >= 1.5
    diversity_count = len(operator_families)
    sample_protection = len(rows) < 10
    if len(rows) < 5:
        light = "YELLOW"
        action = "样本不足，继续补充同方向结构变体。"
    elif dsi >= 0.62 or (signal_probability >= 0.90 and maximum_sharpe >= 1.0):
        light = "GREEN"
        action = "加大预算，围绕高分子群细化参数并做成本压力测试。"
    elif dsi >= 0.42 or ceiling_protection or bimodal_protection:
        light = "YELLOW"
        action = "保留高分子群，补充 1-2 轮结构变体后再判断。"
    elif sample_protection:
        light = "YELLOW"
        action = "样本仍不足 10 个，不做否定判断；继续补充结构变体。"
    elif diversity_count < 4:
        light = "RED"
        action = "当前证据弱，先扩展算子族或字段组合，再评估是否放弃。"
    elif mean_sharpe < noise_floor and maximum_sharpe < 0.75 and pass_rate == 0:
        light = "DEAD"
        action = "多类算子均无信号，记录反模式并切换经济假设。"
    else:
        light = "RED"
        action = "做一次结构性改变，避免继续只调相邻窗口。"
    return _jsonable(
        {
            "name": name,
            "light": light,
            "action": action,
            "sample_count": len(rows),
            "mean_sharpe": mean_sharpe,
            "maximum_sharpe": maximum_sharpe,
            "mean_return": float(np.mean(returns)) if returns else 0.0,
            "signal_probability": signal_probability,
            "significance_method": significance_method,
            "pass_count": pass_count,
            "pass_rate": pass_rate,
            "pass_rate_wilson_lower": pass_rate_lower,
            "consistency": consistency,
            "bimodality_coefficient": bimodality,
            "operator_families": operator_families,
            "operator_family_count": diversity_count,
            "dsi": dsi,
            "protections": {
                "small_sample": sample_protection,
                "high_ceiling": ceiling_protection,
                "bimodal": bimodal_protection,
                "insufficient_operator_diversity": diversity_count < 4,
            },
        }
    )


def _direction_radar(candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in candidate_rows:
        summary = item["metrics"]["rolling_validation"]["summary"]
        rows.append(
            {
                "family": item["spec"].family,
                "sharpe": (summary.get("metrics") or {}).get("sharpe"),
                "return": summary.get("total_return"),
                "passed": bool(item["gate"].get("passed")),
                "operator_families": sorted(_ast_operator_families(item["spec"].ast)),
            }
        )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["family"]), []).append(row)
    family_buckets = [
        _direction_bucket(family_rows, name=family)
        for family, family_rows in sorted(grouped.items())
    ]
    light_order = {"GREEN": 0, "YELLOW": 1, "RED": 2, "DEAD": 3}
    family_buckets.sort(key=lambda item: (light_order[item["light"]], -item["dsi"], item["name"]))
    return {
        "version": "direction-radar-v1",
        "noise_floor_sharpe": 1.0,
        "overall": _direction_bucket(rows, name="all_candidates"),
        "families": family_buckets,
        "confirmation_labels_accessed": False,
    }


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _load_frame(
    req: FactorFactoryStartRequest,
    *,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if req.source == "synthetic":
        frame = dataset_module.generate_dataset(
            preset=req.dataset,
            seed=req.seed,
            n_bars=req.n_bars,
            interval=req.interval,
            start="2024-01-01",
        )
        provenance = {
            "source": "synthetic",
            "dataset": req.dataset,
            "seed": req.seed,
            "symbol": req.symbol,
            "interval": req.interval,
            "fingerprint": market_data_module.fingerprint_frame(frame),
            "offline": True,
        }
    elif req.source == "akshare_live":
        from core.data_feed.akshare_source import AkshareSource

        now = datetime.now(UTC)
        lookback_days = max(30, req.n_bars * 2 if req.interval == "1d" else req.n_bars // 4)
        source = AkshareSource()
        frame = source.get_kline(
            req.symbol,
            req.interval,
            start=now - timedelta(days=lookback_days),
            end=now,
            limit=req.n_bars,
        )
        if frame.empty:
            raise ValueError(f"AkShare 未返回 {req.symbol} 的有效行情")
        frame = frame.tail(req.n_bars).reset_index(drop=True)
        provenance = {
            "source": "akshare_live",
            "symbol": req.symbol,
            "market": req.market,
            "interval": req.interval,
            "fingerprint": market_data_module.fingerprint_frame(frame),
            "fetched_at": now.isoformat(),
            "requested_bars": req.n_bars,
            "offline": False,
            "adjustment": frame.attrs.get("corporate_action_adjustment", "qfq"),
        }
    else:
        live_snapshot_end = (
            market_data_module.current_bar_boundary(req.interval).isoformat()
            if req.source == "okx_live"
            else None
        )
        snapshot = market_data_module.load_market_data(
            req.source,
            symbol=req.symbol,
            interval=req.interval,
            n_bars=req.n_bars,
            end=live_snapshot_end,
            use_cache=not force_refresh,
            allow_partial=True,
        )
        frame = snapshot.df
        provenance = {
            "source": snapshot.source,
            "symbol": snapshot.symbol,
            "interval": snapshot.interval,
            "fingerprint": snapshot.fingerprint,
            **snapshot.provenance,
        }
    normalized = frame.copy().reset_index(drop=True)
    normalized["datetime"] = pd.to_datetime(normalized["datetime"], utc=True)
    normalized = normalized.dropna(subset=["datetime", "close"]).sort_values("datetime")
    normalized = normalized.drop_duplicates("datetime", keep="last").reset_index(drop=True)
    if len(normalized) < 240:
        raise ValueError(f"自动因子研究至少需要 240 根有效 K 线，当前只有 {len(normalized)} 根")
    return normalized, provenance


def _split_frame(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    session_dates = frame["datetime"].dt.date
    unique_dates = list(dict.fromkeys(session_dates.tolist()))
    if len(unique_dates) < 30:
        raise ValueError("自动研究至少需要 30 个不同交易日期")
    validation_date = unique_dates[max(1, int(len(unique_dates) * 0.5))]
    confirmation_date = unique_dates[max(2, int(len(unique_dates) * 0.8))]
    partitions = {
        "discovery": frame[session_dates < validation_date].copy(),
        "rolling_validation": frame[
            (session_dates >= validation_date) & (session_dates < confirmation_date)
        ].copy(),
        "locked_confirmation": frame[session_dates >= confirmation_date].copy(),
    }
    if min(len(item) for item in partitions.values()) < 30:
        raise ValueError("发现集、滚动验证集和确认集都至少需要 30 根 K 线")
    return {key: value.reset_index(drop=True) for key, value in partitions.items()}


def _partition_contract(partitions: dict[str, pd.DataFrame]) -> FactorResearchDataSplit:
    payload: dict[str, FactorResearchDataPartition] = {}
    for key, frame in partitions.items():
        payload[key] = FactorResearchDataPartition(
            start=frame["datetime"].iloc[0].date(),
            end=frame["datetime"].iloc[-1].date(),
            data_fingerprint=market_data_module.fingerprint_frame(frame),
        )
    return FactorResearchDataSplit(
        discovery=payload["discovery"],
        rolling_validation=payload["rolling_validation"],
        locked_confirmation=payload["locked_confirmation"],
        purge_periods=5,
        embargo_periods=1,
    )


def _candidate_ast(family: str, lookback: int) -> dict[str, Any]:
    close = {"op": "field", "name": "close"}
    high = {"op": "field", "name": "high"}
    low = {"op": "field", "name": "low"}
    volume = {"op": "field", "name": "volume"}
    if family.startswith("builtin_"):
        builtin_key = family.removeprefix("builtin_")
        if builtin_key not in FACTOR_META:
            raise ValueError(f"未知内置因子: {builtin_key}")
        return {"op": "builtin_factor", "key": builtin_key}
    if family == "volatility_adjusted_momentum":
        return {
            "op": "rolling_zscore",
            "value": {
                "op": "div",
                "left": {"op": "pct_change", "value": close, "periods": lookback},
                "right": {
                    "op": "rolling_std",
                    "value": {"op": "pct_change", "value": close, "periods": 1},
                    "window": lookback,
                },
            },
            "window": max(40, lookback * 3),
        }
    if family == "liquidity_shock_reversal":
        return {
            "op": "neg",
            "value": {
                "op": "mul",
                "left": {
                    "op": "rolling_zscore",
                    "value": {"op": "pct_change", "value": close, "periods": 1},
                    "window": lookback,
                },
                "right": {
                    "op": "abs",
                    "value": {
                        "op": "rolling_zscore",
                        "value": {"op": "pct_change", "value": volume, "periods": 1},
                        "window": lookback,
                    },
                },
            },
        }
    if family == "volume_confirmed_breakout":
        return {
            "op": "mul",
            "left": {
                "op": "rolling_zscore",
                "value": {"op": "pct_change", "value": close, "periods": lookback},
                "window": max(40, lookback * 3),
            },
            "right": {
                "op": "rank",
                "value": {"op": "pct_change", "value": volume, "periods": 1},
                "window": lookback,
            },
        }
    if family == "dual_moving_average_trend":
        return {
            "op": "rolling_zscore",
            "value": {
                "op": "div",
                "left": {
                    "op": "rolling_mean",
                    "value": close,
                    "window": max(2, lookback // 3),
                },
                "right": {"op": "rolling_mean", "value": close, "window": lookback},
            },
            "window": max(40, lookback * 2),
        }
    if family == "donchian_breakout":
        return {
            "op": "rolling_zscore",
            "value": {
                "op": "div",
                "left": close,
                "right": {
                    "op": "rolling_max",
                    "value": {"op": "lag", "value": close, "periods": 1},
                    "window": lookback,
                },
            },
            "window": max(40, lookback * 2),
        }
    if family == "short_term_reversal":
        return {
            "op": "neg",
            "value": {
                "op": "rolling_zscore",
                "value": {
                    "op": "pct_change",
                    "value": close,
                    "periods": max(1, lookback // 5),
                },
                "window": lookback,
            },
        }
    if family == "range_position_breakout":
        lagged_close = {"op": "lag", "value": close, "periods": 1}
        rolling_low = {"op": "rolling_min", "value": lagged_close, "window": lookback}
        rolling_high = {"op": "rolling_max", "value": lagged_close, "window": lookback}
        return {
            "op": "sub",
            "left": {
                "op": "div",
                "left": {"op": "sub", "left": close, "right": rolling_low},
                "right": {"op": "sub", "left": rolling_high, "right": rolling_low},
            },
            "right": {"op": "const", "value": 0.5},
        }
    if family == "efficiency_ratio_trend":
        one_bar_return = {"op": "pct_change", "value": close, "periods": 1}
        return {
            "op": "rolling_zscore",
            "value": {
                "op": "div",
                "left": {"op": "pct_change", "value": close, "periods": lookback},
                "right": {
                    "op": "rolling_sum",
                    "value": {"op": "abs", "value": one_bar_return},
                    "window": lookback,
                },
            },
            "window": max(48, lookback * 4),
        }
    if family == "volatility_gated_reversal":
        one_bar_return = {"op": "pct_change", "value": close, "periods": 1}
        return {
            "op": "mul",
            "left": {
                "op": "neg",
                "value": {
                    "op": "rolling_zscore",
                    "value": one_bar_return,
                    "window": lookback,
                },
            },
            "right": {
                "op": "rank",
                "value": {
                    "op": "rolling_std",
                    "value": one_bar_return,
                    "window": lookback,
                },
                "window": max(48, lookback * 4),
            },
        }
    if family == "close_location_volume_pressure":
        close_location = {
            "op": "sub",
            "left": {
                "op": "div",
                "left": {"op": "sub", "left": close, "right": low},
                "right": {"op": "sub", "left": high, "right": low},
            },
            "right": {"op": "const", "value": 0.5},
        }
        return {
            "op": "rolling_zscore",
            "value": {
                "op": "rolling_mean",
                "value": {
                    "op": "mul",
                    "left": close_location,
                    "right": {"op": "rank", "value": volume, "window": lookback},
                },
                "window": max(3, lookback // 4),
            },
            "window": max(48, lookback * 4),
        }
    raise ValueError(f"未知自动因子族: {family}")


def _candidate_specs(run_id: str, budget: int, *, interval: str = "1d") -> list[CandidateSpec]:
    core_families = [
        (
            "volatility_adjusted_momentum",
            "波动率调整动量",
            "风险归一化后的中期趋势应比原始动量更稳定。",
            "趋势方向翻转或波动缩放后成本后收益消失。",
        ),
        (
            "liquidity_shock_reversal",
            "流动性冲击反转",
            "价格冲击叠加成交量异常后更可能短期均值回复。",
            "冲击后延续持续占优或高换手吞噬收益。",
        ),
        (
            "volume_confirmed_breakout",
            "成交量确认突破",
            "成交活跃度改善能过滤缺少供需确认的价格突破。",
            "成交量确认不能提升成本后突破收益。",
        ),
    ]
    extension_families = [
        (
            "dual_moving_average_trend",
            "双均线趋势",
            "短周期均价相对长周期均价的强弱可过滤单点价格噪声。",
            "均线差在震荡状态频繁翻转且成本后收益消失。",
        ),
        (
            "donchian_breakout",
            "Donchian 突破",
            "价格突破过去区间高点后，供需失衡可能延续一个再平衡周期。",
            "突破缺乏后续延续或回撤超过预注册上限。",
        ),
        (
            "short_term_reversal",
            "纯短期反转",
            "短周期极端价格变化可能在流动性恢复后均值回复。",
            "短期冲击持续延续或反转收益无法覆盖换手成本。",
        ),
    ]
    builtin_groups = [
        ("trend_strength", "builtin_trend"),
        ("momentum_20", "builtin_trend"),
        ("macd_histogram", "builtin_trend"),
        ("adx_direction", "builtin_trend"),
        ("mean_reversion", "builtin_reversal"),
        ("rsi_reversal", "builtin_reversal"),
        ("bollinger_reversal", "builtin_reversal"),
        ("breakout_20", "builtin_breakout"),
        ("volume_confirmation", "builtin_volume"),
        ("obv_momentum", "builtin_volume"),
        ("chaikin_flow", "builtin_volume"),
    ]
    ordered: list[tuple[tuple[str, str, str, str], int, str, str]] = []
    for family in core_families:
        ordered.append((family, 20, "template", f"factor_factory_{family[0]}"))
    for lookback in (10, 40):
        for family in core_families:
            ordered.append((family, lookback, "random_dsl", f"factor_factory_{family[0]}"))
    for family in extension_families:
        ordered.append((family, 20, "template", f"factor_factory_{family[0]}"))
    for lookback in (10, 40):
        for family in extension_families:
            ordered.append((family, lookback, "random_dsl", f"factor_factory_{family[0]}"))
    for builtin_key, research_family in builtin_groups:
        label, _category, description = FACTOR_META[builtin_key]
        ordered.append(
            (
                (
                    f"builtin_{builtin_key}",
                    label,
                    f"{description}，作为既有公式基线参与同一滚动验证。",
                    "该公式在独立验证窗口方向不稳定或成本后收益消失。",
                ),
                20,
                "template",
                f"factor_factory_{research_family}",
            )
        )
    ordered.append(
        (
            (
                "range_position_breakout",
                "区间位置突破",
                "价格在滞后一周期的高低区间中持续靠近上沿，可能反映供需失衡延续。",
                "区间上沿信号缺少后续延续，或换手成本吞噬收益。",
            ),
            20,
            "symbolic_regression",
            "factor_factory_builtin_breakout",
        )
    )
    if interval == "1h":
        replacements = {
            ("volatility_adjusted_momentum", 10): (
                (
                    "efficiency_ratio_trend",
                    "效率比趋势",
                    "单位价格路径对应的净位移越高，短周期趋势越可能延续。",
                    "净位移效率下降或双倍成本后趋势收益消失。",
                ),
                12,
                "symbolic_regression",
                "factor_factory_efficiency_trend",
            ),
            ("volatility_adjusted_momentum", 40): (
                (
                    "efficiency_ratio_trend",
                    "效率比趋势",
                    "单位价格路径对应的净位移越高，短周期趋势越可能延续。",
                    "净位移效率下降或双倍成本后趋势收益消失。",
                ),
                24,
                "symbolic_regression",
                "factor_factory_efficiency_trend",
            ),
            ("volume_confirmed_breakout", 10): (
                (
                    "volatility_gated_reversal",
                    "高波动反转",
                    "高波动状态中的单根极端价格冲击更可能出现短期流动性修复。",
                    "冲击在高波动状态继续同向扩散或换手成本超过反转收益。",
                ),
                12,
                "symbolic_regression",
                "factor_factory_volatility_gated_reversal",
            ),
            ("volume_confirmed_breakout", 40): (
                (
                    "volatility_gated_reversal",
                    "高波动反转",
                    "高波动状态中的单根极端价格冲击更可能出现短期流动性修复。",
                    "冲击在高波动状态继续同向扩散或换手成本超过反转收益。",
                ),
                24,
                "symbolic_regression",
                "factor_factory_volatility_gated_reversal",
            ),
            ("donchian_breakout", 10): (
                (
                    "close_location_volume_pressure",
                    "量价收盘位置压力",
                    "成交活跃时价格持续收在单根区间上部，可能反映短周期买方压力。",
                    "收盘位置压力不能延续，或成交活跃只放大噪声与成本。",
                ),
                12,
                "symbolic_regression",
                "factor_factory_close_location_pressure",
            ),
            ("donchian_breakout", 40): (
                (
                    "close_location_volume_pressure",
                    "量价收盘位置压力",
                    "成交活跃时价格持续收在单根区间上部，可能反映短周期买方压力。",
                    "收盘位置压力不能延续，或成交活跃只放大噪声与成本。",
                ),
                24,
                "symbolic_regression",
                "factor_factory_close_location_pressure",
            ),
        }
        ordered = [replacements.get((item[0][0], item[1]), item) for item in ordered]
    prefix = run_id[:8]
    specs: list[CandidateSpec] = []
    for (
        (family, label, hypothesis, invalidation),
        lookback,
        source,
        research_family,
    ) in ordered[:budget]:
        specs.append(
            CandidateSpec(
                key=f"ff_{prefix}_{family[:32]}_{lookback}",
                label=f"{label} {lookback}",
                family=research_family,
                source=source,
                lookback=lookback,
                ast=_candidate_ast(family, lookback),
                hypothesis=hypothesis,
                invalidation=invalidation,
            )
        )
    return specs


def _brain_candidate_specs(
    run_id: str,
    proposals: list[AlphaProposal],
) -> list[CandidateSpec]:
    prefix = run_id[:8]
    return [
        CandidateSpec(
            key=f"ff_{prefix}_{proposal.candidate_id}"[:80],
            label=proposal.label[:100],
            family=proposal.family[:80],
            source=proposal.source,
            lookback=0,
            ast=proposal.ast,
            hypothesis=proposal.hypothesis,
            invalidation=proposal.invalidation,
            falsification_tests=proposal.falsification_tests,
            model=proposal.model,
            prompt=proposal.prompt,
            ai_trace=proposal.ai_trace,
        )
        for proposal in proposals
    ]


def _manual_candidate_specs(
    run_id: str,
    req: FactorFactoryStartRequest,
) -> list[CandidateSpec]:
    prefix = run_id[:8]
    specs: list[CandidateSpec] = []
    for index, candidate in enumerate(req.manual_candidates, start=1):
        candidate_id = (candidate.candidate_id or f"manual_alpha_{index}").lower().replace("-", "_")
        ast = candidate.formula_ast or parse_alpha_expression(str(candidate.expression))
        specs.append(
            CandidateSpec(
                key=f"ff_{prefix}_{candidate_id}"[:80],
                label=candidate.label or candidate_id.replace("_", " "),
                family=candidate.family,
                source="human",
                lookback=0,
                ast=ast,
                hypothesis=candidate.hypothesis,
                invalidation=candidate.invalidation,
                falsification_tests=tuple(candidate.falsification_tests),
            )
        )
    return specs


def _candidate_generation_fingerprint(
    req: FactorFactoryStartRequest,
    *,
    data_fingerprint: str,
) -> str:
    payload = {
        "research_version": FACTOR_FACTORY_RESEARCH_VERSION,
        "alpha_mining_version": ALPHA_MINING_VERSION,
        "ai_prompt_version": AI_PROMPT_VERSION,
        "request": req.model_dump(mode="json"),
        "data_fingerprint": data_fingerprint,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _discovery_screen_score(summary: dict[str, Any]) -> float:
    sharpe = float((summary.get("metrics") or {}).get("sharpe") or 0.0)
    total_return = float(summary.get("total_return") or 0.0)
    drawdown = max(abs(float(summary.get("max_drawdown") or 0.0)), 0.01)
    rank_ic = float(summary.get("rank_ic") or 0.0)
    stability = summary.get("window_stability") or {}
    positive_window_ratio = float(stability.get("positive_window_ratio") or 0.0)
    return sharpe + total_return / drawdown + rank_ic * 2.0 + positive_window_ratio * 0.25


def _prior_direction_radar(req: FactorFactoryStartRequest) -> dict[str, Any] | None:
    for run in store.list_factor_factory_runs(limit=200):
        config = run.get("config") or {}
        result = run.get("result") or {}
        radar = result.get("direction_radar")
        if not isinstance(radar, dict):
            continue
        if (
            config.get("market") == req.market
            and str(config.get("symbol") or "").upper() == req.symbol.upper()
            and config.get("interval") == req.interval
        ):
            families = []
            for item in radar.get("families") or []:
                if not isinstance(item, dict):
                    continue
                families.append(
                    {
                        key: item.get(key)
                        for key in (
                            "name",
                            "light",
                            "action",
                            "sample_count",
                            "dsi",
                            "mean_sharpe",
                            "maximum_sharpe",
                            "operator_families",
                        )
                    }
                )
            return {
                "run_id": run["id"],
                "overall": {
                    key: (radar.get("overall") or {}).get(key)
                    for key in ("light", "action", "sample_count", "dsi", "maximum_sharpe")
                },
                "families": families[:20],
                "confirmation_labels_accessed": False,
            }
    return None


def _select_diverse_ranked(
    ranked: list[tuple[float, CandidateSpec, AlphaProposal, dict[str, Any]]],
    count: int,
    *,
    prior_family_lights: dict[str, str] | None = None,
) -> list[tuple[float, CandidateSpec, AlphaProposal, dict[str, Any]]]:
    if count <= 0:
        return []
    remaining = list(ranked)
    selected: list[tuple[float, CandidateSpec, AlphaProposal, dict[str, Any]]] = []
    family_counts: Counter[str] = Counter()
    operator_families: set[str] = set()
    prior_lights = prior_family_lights or {}
    family_limit = max(2, math.ceil(count / 4))
    maximum_score = max((item[0] for item in ranked), default=0.0)
    minimum_score = min((item[0] for item in ranked), default=0.0)
    score_span = max(maximum_score - minimum_score, 1e-9)
    while remaining and len(selected) < count:
        eligible = [item for item in remaining if family_counts[item[2].family] < family_limit]
        pool = eligible or remaining

        def utility(item: tuple[float, CandidateSpec, AlphaProposal, dict[str, Any]]) -> float:
            score, _spec, proposal, _summary = item
            normalized_score = (score - minimum_score) / score_span
            families = _ast_operator_families(proposal.ast)
            family_bonus = 0.30 if family_counts[proposal.family] == 0 else 0.0
            operator_bonus = min(0.24, 0.06 * len(families - operator_families))
            concentration_penalty = 0.05 * family_counts[proposal.family]
            history_adjustment = {
                "GREEN": 0.16,
                "YELLOW": 0.08,
                "RED": -0.08,
                "DEAD": -0.40,
            }.get(prior_lights.get(proposal.family, ""), 0.0)
            return (
                normalized_score
                + family_bonus
                + operator_bonus
                + history_adjustment
                - concentration_penalty
            )

        chosen = max(pool, key=lambda item: (utility(item), item[0], item[1].key))
        selected.append(chosen)
        remaining.remove(chosen)
        family_counts[chosen[2].family] += 1
        operator_families.update(_ast_operator_families(chosen[2].ast))
    return selected


def _staged_brain_candidate_specs(
    run_id: str,
    req: FactorFactoryStartRequest,
    *,
    generation_fingerprint: str,
    discovery: pd.DataFrame,
) -> tuple[list[CandidateSpec], dict[str, Any]]:
    prior_radar = _prior_direction_radar(req)
    prior_family_lights = {
        str(item.get("name")): str(item.get("light"))
        for item in (prior_radar or {}).get("families", [])
        if item.get("name")
    }
    seed = int(hashlib.sha256(generation_fingerprint.encode("utf-8")).hexdigest()[:16], 16)
    pool_size = min(90, max(req.candidate_budget * 3, req.candidate_budget + 12))
    grammar_proposals = generate_grammar_proposals(
        seed=seed,
        count=pool_size,
        interval=req.interval,
        market=req.market,
    )
    grammar_specs = _brain_candidate_specs(run_id, grammar_proposals)
    screened_specs, rejected, preflight = _candidate_preflight(
        grammar_specs,
        discovery,
        budget=pool_size,
    )
    proposal_by_key = dict(
        zip((item.key for item in grammar_specs), grammar_proposals, strict=True)
    )
    ranked: list[tuple[float, CandidateSpec, AlphaProposal, dict[str, Any]]] = []
    discovery_rejected: dict[str, dict[str, Any]] = {}
    minimum_observations = max(30, min(120, int(len(discovery) * 0.35)))
    for spec in screened_specs:
        signal = evaluate_factor_ast(spec.ast, discovery)
        valid_observations = int(pd.Series(signal).notna().sum())
        if valid_observations < minimum_observations:
            discovery_rejected[spec.key] = {
                "reason": "insufficient_signal_coverage",
                "valid_observations": valid_observations,
                "minimum_observations": minimum_observations,
            }
            continue
        result = _backtest_partition(discovery, signal, req=req)
        summary = result["summary"]
        if int(summary.get("n_trades") or 0) < 2:
            discovery_rejected[spec.key] = {
                "reason": "insufficient_discovery_trades",
                "n_trades": int(summary.get("n_trades") or 0),
                "minimum_trades": 2,
            }
            continue
        ranked.append(
            (
                _discovery_screen_score(summary),
                spec,
                proposal_by_key[spec.key],
                summary,
            )
        )
    light_priority = {"GREEN": 0, "YELLOW": 1, "RED": 2, "DEAD": 3}
    ranked.sort(
        key=lambda item: (
            light_priority.get(prior_family_lights.get(item[2].family, ""), 1),
            -item[0],
            item[1].key,
        )
    )
    if len(ranked) < req.candidate_budget:
        raise RuntimeError(
            f"discovery screen retained {len(ranked)} of {req.candidate_budget} required candidates"
        )

    ai_requested = min(req.candidate_budget, req.ai_candidate_count) if req.use_ai else 0
    seed_count = min(len(ranked), max(3, ai_requested)) if ai_requested else 0
    diversified_seeds = _select_diverse_ranked(
        ranked,
        seed_count,
        prior_family_lights=prior_family_lights,
    )
    ai_seeds = [
        {
            "candidate_id": proposal.candidate_id,
            "family": proposal.family,
            "formula_ast": proposal.ast,
            "hypothesis": proposal.hypothesis,
            "discovery_metrics": {
                "screen_score": score,
                "total_return": summary.get("total_return"),
                "max_drawdown": summary.get("max_drawdown"),
                "sharpe": (summary.get("metrics") or {}).get("sharpe"),
                "rank_ic": summary.get("rank_ic"),
                "n_trades": summary.get("n_trades"),
                "window_stability": summary.get("window_stability"),
            },
        }
        for score, _spec, proposal, summary in diversified_seeds
    ]
    ai_proposals, ai_audit = generate_ai_proposals(
        brief=req.alpha_brief,
        interval=req.interval,
        count=ai_requested,
        market=req.market,
        maximum_tokens=req.maximum_ai_tokens,
        provider=req.ai_provider,
        seed_candidates=ai_seeds,
        prior_direction_radar=prior_radar,
    )

    retained_grammar_count = req.candidate_budget - len(ai_proposals)
    diversified_grammar = _select_diverse_ranked(
        ranked,
        retained_grammar_count,
        prior_family_lights=prior_family_lights,
    )
    selected_proposals = [
        *(item[2] for item in diversified_grammar),
        *ai_proposals,
    ]
    formula_hashes: set[str] = set()
    unique: list[AlphaProposal] = []
    for proposal in [*selected_proposals, *(item[2] for item in ranked)]:
        definition = FactorDefinition(
            key=proposal.candidate_id[:80],
            label=proposal.label,
            market=req.market,
            ast=proposal.ast,
            family=proposal.family,
        )
        if definition.formula_hash in formula_hashes:
            continue
        formula_hashes.add(definition.formula_hash)
        unique.append(proposal)
        if len(unique) == req.candidate_budget:
            break
    if len(unique) < req.candidate_budget:
        raise RuntimeError(f"staged alpha mining produced {len(unique)} unique candidates")

    selected_specs = _brain_candidate_specs(run_id, unique)
    selected_ids = {item.candidate_id for item in unique}
    return selected_specs, {
        "version": ALPHA_MINING_VERSION,
        "mode": "grammar_screen_then_ai_refine",
        "brief": req.alpha_brief,
        "candidate_count": len(selected_specs),
        "source_counts": dict(Counter(item.source for item in selected_specs)),
        "stages": {
            "grammar_generation": {
                "candidate_count": len(grammar_specs),
                "estimated_compute_units": len(grammar_specs) * len(discovery),
            },
            "discovery_preflight": {
                **preflight,
                "rejections": {**rejected, **discovery_rejected},
            },
            "discovery_backtest": {
                "ranked_candidates": len(ranked),
                "seed_candidate_ids": [item["candidate_id"] for item in ai_seeds],
                "selected_candidate_ids": sorted(selected_ids),
                "selected_family_count": len({item.family for item in unique}),
                "selected_operator_families": sorted(
                    {family for item in unique for family in _ast_operator_families(item.ast)}
                ),
                "confirmation_labels_accessed": False,
            },
            "ai_refinement": ai_audit,
            "prior_direction_radar": prior_radar,
        },
        "ai": ai_audit,
        "confirmation_labels_exposed": False,
        "dynamic_code_execution": False,
    }


def _candidate_specs_for_request(
    run_id: str,
    req: FactorFactoryStartRequest,
    *,
    generation_fingerprint: str,
    discovery: pd.DataFrame,
) -> tuple[list[CandidateSpec], dict[str, Any]]:
    if req.candidate_mode == "manual":
        specs = _manual_candidate_specs(run_id, req)
        audit = {
            "version": "manual-alpha-v1",
            "mode": "manual",
            "candidate_count": len(specs),
            "source_counts": {"human": len(specs)},
            "confirmation_labels_exposed": False,
            "dynamic_code_execution": False,
        }
    elif req.candidate_mode == "library":
        specs = _candidate_specs(run_id, req.candidate_budget, interval=req.interval)
        audit: dict[str, Any] = {
            "version": "factor-library-v2.5",
            "mode": "library",
            "candidate_count": len(specs),
            "source_counts": dict(Counter(spec.source for spec in specs)),
            "confirmation_labels_exposed": False,
            "dynamic_code_execution": False,
        }
    else:
        specs, audit = _staged_brain_candidate_specs(
            run_id,
            req,
            generation_fingerprint=generation_fingerprint,
            discovery=discovery,
        )
    manifest = []
    for spec in specs:
        definition = FactorDefinition(
            key=spec.key,
            label=spec.label,
            market=req.market,
            ast=spec.ast,
            family=spec.family,
        )
        validation = validate_factor_definition(definition)
        manifest.append(
            {
                "candidate_key": spec.key,
                "label": spec.label,
                "family": spec.family,
                "source": spec.source,
                "formula_hash": definition.formula_hash,
                "formula_complexity": validation.operators,
            }
        )
    return specs, {**audit, "manifest": manifest}


def _record_ai_search_round(
    plan_id: str,
    specs: list[CandidateSpec],
    generation_audit: dict[str, Any],
) -> None:
    ai_specs = [spec for spec in specs if spec.source == "ai"]
    if not ai_specs:
        return
    ai_audit = generation_audit.get("ai", {})
    complexities = []
    for spec in ai_specs:
        validation = validate_factor_definition(
            FactorDefinition(
                key=spec.key,
                label=spec.label,
                market="crypto",
                ast=spec.ast,
                family=spec.family,
            )
        )
        complexities.append(validation.operators)
    response = validate_factor_ai_search_round(
        plan_id,
        FactorAiSearchRoundRequest(
            round_id="brain_alpha_generation_1",
            candidate_count=len(ai_specs),
            duplicate_count=0,
            formula_complexities=complexities,
            llm_tokens=int((ai_audit.get("token_usage") or {}).get("total_tokens", 0)),
            input_fingerprint=str(ai_audit["input_fingerprint"]),
            approved_by="factor-factory-request",
            approved_candidate_ids=[spec.key for spec in ai_specs],
            budget_approved_ack=True,
        ),
    )
    if not response.get("ok") or response.get("gate_violations"):
        raise ValueError(response.get("error") or "AI 候选搜索轮次未通过预算治理")


def _candidate_preflight(
    specs: list[CandidateSpec],
    discovery: pd.DataFrame,
    *,
    budget: int,
) -> tuple[list[CandidateSpec], dict[str, dict[str, Any]], dict[str, Any]]:
    order = {spec.key: index for index, spec in enumerate(specs)}
    by_key = {spec.key: spec for spec in specs}
    formula_owner: dict[str, str] = {}
    signals: dict[str, pd.Series] = {}
    rejected: dict[str, dict[str, Any]] = {}
    for spec in specs:
        definition = FactorDefinition(
            key=spec.key,
            label=spec.label,
            market="crypto",
            ast=spec.ast,
            family=spec.family,
        )
        duplicate_of = formula_owner.get(definition.formula_hash)
        if duplicate_of is not None:
            rejected[spec.key] = {
                "reason": "formula_duplicate",
                "kept_candidate": duplicate_of,
                "formula_hash": definition.formula_hash,
            }
            continue
        formula_owner[definition.formula_hash] = spec.key
        signals[spec.key] = evaluate_factor_ast(spec.ast, discovery)

    correlations = detect_series_redundancy(
        signals,
        minimum_observations=max(30, min(120, len(discovery) // 3)),
        high_correlation_threshold=0.985,
    )
    for relation in correlations:
        left_key = str(relation["left_key"])
        right_key = str(relation["right_key"])
        kept_key, blocked_key = sorted((left_key, right_key), key=order.__getitem__)
        if blocked_key in rejected:
            continue
        same_direction = relation.get("direction") == "same"
        cross_family = by_key[left_key].family != by_key[right_key].family
        relation_name = str(relation["relation"])
        equivalent = relation_name in {
            "exact_duplicate",
            "constant_multiple",
            "monotonic_equivalent",
        }
        if not same_direction or not (
            equivalent or (cross_family and relation_name == "high_correlation")
        ):
            continue
        rejected[blocked_key] = {
            "reason": "correlation_cluster",
            "kept_candidate": kept_key,
            "relation": relation_name,
            "pearson": relation.get("pearson"),
            "spearman": relation.get("spearman"),
            "observations": relation.get("observations"),
        }

    accepted = [spec for spec in specs if spec.key not in rejected]
    duplicate_count = sum(detail["reason"] == "formula_duplicate" for detail in rejected.values())
    audit = {
        "generated_candidates": len(specs),
        "accepted_candidates": len(accepted),
        "rejected_candidates": len(rejected),
        "formula_duplicate_count": duplicate_count,
        "correlation_cluster_rejections": len(rejected) - duplicate_count,
        "candidate_budget": budget,
        "within_budget": len(specs) <= budget,
        "duplicate_rate": duplicate_count / len(specs) if specs else 0.0,
        "maximum_duplicate_rate": 0.35,
        "within_duplicate_rate": duplicate_count / len(specs) <= 0.35 if specs else True,
        "discovery_only": True,
        "confirmation_labels_accessed": False,
        "correlation_threshold": 0.985,
        "rejections": rejected,
    }
    return accepted, rejected, audit


def _candidate_universe_hash(specs: list[CandidateSpec]) -> str:
    payload = [
        {
            "family": spec.family,
            "source": spec.source,
            "lookback": spec.lookback,
            "ast": spec.ast,
            "hypothesis": spec.hypothesis,
            "invalidation": spec.invalidation,
            "falsification_tests": spec.falsification_tests,
            "model": spec.model,
            "prompt": spec.prompt,
        }
        for spec in specs
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _research_fingerprint(
    req: FactorFactoryStartRequest,
    *,
    data_fingerprint: str,
    candidate_universe_hash: str,
) -> str:
    payload = {
        "research_version": FACTOR_FACTORY_RESEARCH_VERSION,
        "request": req.model_dump(mode="json"),
        "data_fingerprint": data_fingerprint,
        "candidate_universe_hash": candidate_universe_hash,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _periods_per_year(interval: str) -> int:
    return {"1h": 8_760, "4h": 2_190, "1d": 365}[interval]


def _return_series(result: dict[str, Any]) -> list[float]:
    equity = pd.Series([item["equity"] for item in result["equity_curve"]], dtype=float)
    return [float(item) for item in equity.pct_change().dropna() if math.isfinite(float(item))]


def _p_value(returns: list[float]) -> float:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 3 or float(np.std(values, ddof=1)) <= 1e-12:
        return 1.0
    statistic = float(np.mean(values) / (np.std(values, ddof=1) / math.sqrt(len(values))))
    return float(math.erfc(abs(statistic) / math.sqrt(2)))


def _spearman(left: pd.Series, right: pd.Series) -> float:
    aligned = pd.concat(
        [pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")],
        axis=1,
    ).dropna()
    if len(aligned) < 3:
        return 0.0
    left_rank = aligned.iloc[:, 0].rank(pct=True)
    right_rank = aligned.iloc[:, 1].rank(pct=True)
    if left_rank.nunique() < 2 or right_rank.nunique() < 2:
        return 0.0
    value = left_rank.corr(right_rank)
    return float(value) if pd.notna(value) else 0.0


def _signal_ic(frame: pd.DataFrame, signal: pd.Series) -> float:
    executable = pd.Series(signal, dtype=float).shift(1)
    returns = frame["close"].astype(float).pct_change()
    return _spearman(executable, returns)


def _window_stability(returns: list[float], *, windows: int = 3) -> dict[str, Any]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if windows < 1 or len(values) < windows:
        return {
            "windows": windows,
            "period_returns": [],
            "positive_windows": 0,
            "positive_window_ratio": 0.0,
            "return_dispersion": None,
            "passed": False,
        }
    period_returns = [float(np.prod(1 + chunk) - 1) for chunk in np.array_split(values, windows)]
    positive_windows = sum(value >= 0 for value in period_returns)
    required_windows = windows // 2 + 1
    return {
        "windows": windows,
        "period_returns": period_returns,
        "positive_windows": positive_windows,
        "positive_window_ratio": positive_windows / windows,
        "return_dispersion": float(np.std(period_returns)),
        "passed": positive_windows >= required_windows,
    }


def _backtest_partition(
    frame: pd.DataFrame,
    signal: pd.Series,
    *,
    req: FactorFactoryStartRequest,
    commission_bps: float | None = None,
) -> dict[str, Any]:
    applied_commission_bps = (
        req.commission_bps if commission_bps is None else max(0.0, commission_bps)
    )
    result = run_signal_backtest(
        frame.reset_index(drop=True),
        pd.Series(signal).reset_index(drop=True),
        initial_capital=req.initial_capital,
        commission=applied_commission_bps / 10_000,
        periods_per_year=_periods_per_year(req.interval),
    )
    returns = _return_series(result)
    summary = {
        "total_return": result["total_return"],
        "max_drawdown": result["max_drawdown"],
        "n_trades": result["n_trades"],
        "metrics": result["metrics"],
        "raw_p_value": _p_value(returns),
        "effective_sample_size": max(1, len(returns)),
        "rank_ic": _signal_ic(
            frame.reset_index(drop=True), pd.Series(signal).reset_index(drop=True)
        ),
        "window_stability": _window_stability(returns),
    }
    return {
        "summary": _jsonable(summary),
        "returns": returns,
        "assumptions": {"commission_bps": applied_commission_bps},
    }


def _preliminary_gate(metrics: dict[str, Any], req: FactorFactoryStartRequest) -> dict:
    validation = metrics["rolling_validation"]["summary"]
    cost_stress = metrics.get("rolling_validation_cost_stress", metrics["rolling_validation"])[
        "summary"
    ]
    discovery = metrics["discovery"]["summary"]
    validation_stability = validation.get("window_stability") or {}
    cost_stress_stability = cost_stress.get("window_stability") or {}
    thresholds = req.thresholds
    checks = {
        "validation_return": validation["total_return"] >= thresholds.minimum_validation_return,
        "validation_drawdown": abs(validation["max_drawdown"]) <= thresholds.maximum_drawdown,
        "validation_sharpe": float(validation["metrics"].get("sharpe") or 0)
        >= thresholds.minimum_validation_sharpe,
        "minimum_trades": int(validation["n_trades"]) >= thresholds.minimum_trades,
        "direction_consistency": discovery["total_return"] * validation["total_return"] >= 0,
        "validation_window_majority": bool(validation_stability.get("passed")),
        "validation_p_value": float(validation.get("raw_p_value", 1.0))
        <= thresholds.maximum_p_value,
        "validation_rank_ic_direction": float(validation.get("rank_ic") or 0) >= 0,
        "cost_stress_return": cost_stress["total_return"] >= thresholds.minimum_validation_return,
        "cost_stress_drawdown": abs(cost_stress["max_drawdown"]) <= thresholds.maximum_drawdown,
        "cost_stress_sharpe": float(cost_stress["metrics"].get("sharpe") or 0)
        >= thresholds.minimum_validation_sharpe,
        "cost_stress_window_majority": bool(cost_stress_stability.get("passed")),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _score(metrics: dict[str, Any]) -> float:
    validation = metrics["rolling_validation"]["summary"]
    cost_stress = metrics.get("rolling_validation_cost_stress", metrics["rolling_validation"])[
        "summary"
    ]
    sharpe = float(validation["metrics"].get("sharpe") or 0)
    drawdown = max(abs(float(validation["max_drawdown"])), 0.01)
    cost_stress_sharpe = float(cost_stress["metrics"].get("sharpe") or 0)
    cost_stress_drawdown = max(abs(float(cost_stress["max_drawdown"])), 0.01)
    stability = validation.get("window_stability") or {}
    positive_ratio = float(stability.get("positive_window_ratio") or 0)
    dispersion = float(stability.get("return_dispersion") or 0)
    base_quality = sharpe + float(validation["total_return"]) / drawdown
    stressed_quality = (
        cost_stress_sharpe + float(cost_stress["total_return"]) / cost_stress_drawdown
    )
    return round(
        0.5 * base_quality + 0.5 * stressed_quality + 0.5 * positive_ratio - 2 * dispersion,
        8,
    )


def _regime_stability(
    frame: pd.DataFrame,
    signal: pd.Series,
    commission: float,
) -> dict[str, Any]:
    returns = frame["close"].astype(float).pct_change()
    executable = pd.Series(signal, dtype=float).shift(1).fillna(0).clip(0, 1)
    turnover = executable.diff().abs().fillna(executable.abs())
    strategy_returns = executable * returns.fillna(0) - turnover * commission
    volatility = returns.rolling(10, min_periods=5).std()
    median = float(volatility.median()) if volatility.notna().any() else 0.0
    low = strategy_returns[volatility <= median].dropna()
    high = strategy_returns[volatility > median].dropna()
    low_mean = float(low.mean()) if len(low) else -1.0
    high_mean = float(high.mean()) if len(high) else -1.0
    passed = len(low) >= 10 and len(high) >= 10 and min(low_mean, high_mean) >= -0.001
    return {
        "scope": "confirmation_volatility_regimes",
        "low_volatility_mean_return": low_mean,
        "high_volatility_mean_return": high_mean,
        "low_observations": len(low),
        "high_observations": len(high),
        "passed": passed,
    }


def _experiment_event(
    experiment_id: str,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict:
    response = append_factor_experiment_event(
        experiment_id,
        FactorExperimentEventCreate(
            status=status,
            result=result or {},
            evidence=evidence or {},
        ),
    )
    if not response.get("ok"):
        raise ValueError(response.get("error") or "因子实验状态写入失败")
    return response["experiment"]


def _base_lifecycle_evidence(
    definition: dict[str, Any],
    *,
    data_hash: str,
    attempts: int,
    start: str,
    end: str,
    req: FactorFactoryStartRequest,
) -> dict[str, Any]:
    return {
        "formula_definition_hash": definition["definition_hash"],
        "formula_hash": definition["formula_hash"],
        "formula_version": definition["version"],
        "data_snapshot_hash": data_hash,
        "cumulative_attempts": attempts,
        "validation_window": {"start": start, "end": end},
        "cost_profile_version": f"factor-factory-{req.commission_bps:g}bps-v1",
        "gate_version": "factor-factory-locked-oos-v1",
        "live_trading_enabled": False,
    }


def _register_candidate(
    spec: CandidateSpec,
    req: FactorFactoryStartRequest,
) -> dict[str, Any]:
    payload = FactorDefinitionCreate(
        key=spec.key,
        label=spec.label,
        market=req.market,
        ast=spec.ast,
        direction="positive",
        horizon=req.horizon,
        availability_lag=1,
        rationale=f"{spec.hypothesis} 失效条件：{spec.invalidation}",
        family=spec.family,
        version="1.0.0",
        parameters={
            "source": spec.source,
            "lookback": spec.lookback,
            "interval": req.interval,
            "invalidation_condition": spec.invalidation,
            "falsification_tests": list(spec.falsification_tests),
            "candidate_mode": req.candidate_mode,
            "model": spec.model,
            "prompt": spec.prompt,
        },
    )
    response = register_factor_definition(payload)
    if response.get("ok"):
        return response["definition"]
    candidate = FactorDefinition(**payload.model_dump())
    existing = next(
        (
            item
            for item in store.list_factor_definitions(market=req.market)
            if item["formula_hash"] == candidate.formula_hash
        ),
        None,
    )
    if existing is not None:
        return existing
    raise ValueError(response.get("error") or f"候选 {spec.key} 注册失败")


def _detail(run: dict[str, Any]) -> dict[str, Any]:
    observations = store.list_factor_factory_observations(run["id"])
    candidates = [
        {
            **candidate,
            "definition": store.get_factor_definition(
                candidate["factor_key"], candidate["factor_version"]
            ),
        }
        for candidate in store.list_factor_factory_candidates(run["id"])
    ]
    paper = run.get("result", {}).get("paper", {})
    account_id = paper.get("account_id")
    simulation_orders = (
        store.list_simulation_orders(account_id=str(account_id), limit=10_000) if account_id else []
    )
    return {
        "ok": True,
        "run": run,
        "candidates": candidates,
        "observations": observations,
        "simulation_orders": simulation_orders,
        "observation_summary": {
            "count": len(observations),
            "latest_equity": observations[-1]["equity"] if observations else None,
            "after_cost_return": (
                observations[-1]["equity"] / float(run["config"]["initial_capital"]) - 1
                if observations
                else None
            ),
            "max_drawdown": min((item["drawdown"] for item in observations), default=0.0),
        },
        "live_trading_enabled": False,
    }


def _archive_observation_summary(run: dict[str, Any]) -> dict[str, Any]:
    observations = store.list_factor_factory_observations(run["id"])
    initial_capital = float(run.get("config", {}).get("initial_capital") or 0.0)
    return {
        "count": len(observations),
        "first_id": observations[0]["id"] if observations else None,
        "latest_id": observations[-1]["id"] if observations else None,
        "observed_from": observations[0]["market_time"] if observations else None,
        "observed_to": observations[-1]["market_time"] if observations else None,
        "latest_equity": observations[-1]["equity"] if observations else None,
        "after_cost_return": (
            observations[-1]["equity"] / initial_capital - 1
            if observations and initial_capital > 0
            else None
        ),
        "maximum_drawdown": min((item["drawdown"] for item in observations), default=0.0),
        "minimum_fill_rate": min((item["fill_rate"] for item in observations), default=None),
    }


def _archive_run_evidence(
    run: dict[str, Any],
    candidate: dict[str, Any],
    material: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(run.get("result") or {})
    config = dict(run.get("config") or {})
    paper = dict(result.get("paper") or {})
    if material is None:
        account_id = paper.get("account_id")
        orders = (
            store.list_simulation_orders(account_id=str(account_id), limit=10_000)
            if account_id
            else []
        )
        material = {
            "observation_summary": _archive_observation_summary(run),
            "simulation_orders": [
                {
                    "id": item["id"],
                    "status": item["status"],
                    "side": item["side"],
                    "quantity": item["quantity"],
                    "filled_quantity": item["filled_quantity"],
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                    "execution_ids": [execution["id"] for execution in item.get("executions", [])],
                }
                for item in orders
            ],
        }
    return {
        "run_id": run["id"],
        "research_plan_id": run["research_plan_id"],
        "status": run["status"],
        "started_at": run["started_at"],
        "updated_at": run["updated_at"],
        "observation_started_at": run.get("observation_started_at"),
        "observation_ends_at": run.get("observation_ends_at"),
        "scope": {
            "source": config.get("source"),
            "symbol": config.get("symbol"),
            "interval": config.get("interval"),
            "paper_target": config.get("paper_target"),
        },
        "candidate": candidate,
        "data_provenance": config.get("data_provenance") or result.get("data_provenance") or {},
        "data_split": config.get("data_split") or {},
        "confirmation_gate": result.get("confirmation_gate") or {},
        "research_metrics": result.get("research_metrics") or {},
        "simulation_validation": result.get("simulation_validation") or {},
        "paper_evidence": {
            "mode": paper.get("mode"),
            "target": paper.get("target"),
            "started_at": paper.get("started_at"),
            "ends_at": paper.get("ends_at"),
            "completed_rebalance_cycles": paper.get("completed_rebalance_cycles", 0),
            "execution_records": paper.get("execution_records") or [],
            "simulation_order_ids": paper.get("simulation_order_ids") or [],
            "okx_demo": paper.get("okx_demo"),
            "live_trading_enabled": False,
        },
        "observation_summary": material["observation_summary"],
        "simulation_orders": material["simulation_orders"],
    }


def _archive_remaining_risks(state: str, latest_run: dict[str, Any] | None) -> list[str]:
    risks: list[str] = []
    if state == "draft":
        risks.append("candidate_data_validation_not_completed")
    elif state == "exploratory":
        risks.append("locked_confirmation_not_passed")
    elif state == "research_passed":
        risks.append("simulation_observation_not_completed")
    elif state == "degraded":
        risks.append("monitoring_gate_failed")
    elif state == "retired":
        risks.append("factor_retired")

    if latest_run is None:
        risks.append("no_factor_factory_run")
        return risks

    status = str(latest_run["status"])
    if status == "no_qualified_factor":
        risks.append("rolling_validation_not_passed")
    elif status == "no_research_passed_factor":
        risks.append("locked_confirmation_not_passed")
    elif status == "paper_observing":
        risks.append("observation_period_incomplete")
    elif status == "paper_rejected":
        risks.append("simulation_gate_not_passed")
    elif status == "failed":
        risks.append("factor_factory_run_failed")

    confirmation_checks = latest_run.get("confirmation_gate", {}).get("checks", {})
    risks.extend(
        f"confirmation:{name}" for name, passed in confirmation_checks.items() if passed is False
    )
    risks.extend(
        f"simulation:{name}"
        for name in latest_run.get("simulation_validation", {}).get("violations", [])
    )
    return list(dict.fromkeys(risks))


def _archive_admission_gate(
    run_evidence: list[dict[str, Any]],
    lifecycle_events: list[dict[str, Any]],
) -> dict[str, Any]:
    validated_lifecycle = any(item.get("state") == "trading_validated" for item in lifecycle_events)
    maximum_observed_seconds = 0.0
    qualifying_run_id: str | None = None
    simulation_gate_passed = False
    for evidence in run_evidence:
        validation = evidence.get("simulation_validation") or {}
        observed_seconds = max(0.0, float(validation.get("observed_seconds") or 0.0))
        maximum_observed_seconds = max(maximum_observed_seconds, observed_seconds)
        run_simulation_passed = validation.get("eligible_for_trading_validated") is True
        if run_simulation_passed:
            simulation_gate_passed = True
        if (
            evidence.get("status") == "trading_validated"
            and run_simulation_passed
            and validation.get("observation_period_completed") is True
            and observed_seconds >= ARCHIVE_MINIMUM_OBSERVATION_SECONDS
        ):
            qualifying_run_id = str(evidence["run_id"])
            break
    duration_passed = maximum_observed_seconds >= ARCHIVE_MINIMUM_OBSERVATION_SECONDS
    checks = {
        "minimum_seven_real_days": duration_passed,
        "simulation_gate_passed": simulation_gate_passed,
        "trading_validated_lifecycle": validated_lifecycle,
        "qualifying_run_recorded": qualifying_run_id is not None,
    }
    return {
        "eligible": all(checks.values()),
        "required_observation_days": ARCHIVE_MINIMUM_OBSERVATION_DAYS,
        "observed_seconds": maximum_observed_seconds,
        "observed_days": maximum_observed_seconds / 86_400,
        "qualifying_run_id": qualifying_run_id,
        "checks": checks,
        "violations": [name for name, passed in checks.items() if not passed],
    }


def _archive_preregistration(experiment: dict[str, Any]) -> dict[str, Any]:
    provenance = dict(experiment.get("provenance") or {})
    return {
        "experiment_id": experiment["id"],
        "research_plan_id": experiment["research_plan_id"],
        "attempt_number": experiment["attempt_number"],
        "hypothesis": experiment["hypothesis"],
        "source": experiment["source"],
        "data_window": {
            "start": experiment.get("data_start"),
            "end": experiment.get("data_end"),
        },
        "parameter_grid": experiment.get("parameter_grid") or {},
        "parameter_combinations": experiment.get("parameter_combinations", 0),
        "estimated_compute_units": experiment.get("estimated_compute_units", 0),
        "proposal": experiment.get("proposal") or {},
        "pre_registration": experiment.get("pre_registration") or {},
        "provenance": {
            key: provenance.get(key)
            for key in (
                "schema_version",
                "formula",
                "data",
                "experiment",
                "model",
                "prompt",
                "cost",
            )
            if provenance.get(key) is not None
        },
        "created_at": experiment["created_at"],
    }


def _archive_post_study_experiment(experiment: dict[str, Any]) -> dict[str, Any]:
    provenance = dict(experiment.get("provenance") or {})
    return {
        "experiment_id": experiment["id"],
        "research_plan_id": experiment["research_plan_id"],
        "attempt_number": experiment["attempt_number"],
        "status": experiment["status"],
        "events": experiment.get("events") or [],
        "result_provenance": provenance.get("result") or {},
    }


def list_factor_factory_archive(
    *, lifecycle_state: str | None = None, eligible_only: bool = True, limit: int = 100
) -> dict[str, Any]:
    """Build a read-only evidence archive without mutating lifecycle or trading state."""

    runs = store.list_factor_factory_runs(limit=10_000)
    run_links: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for run in runs:
        for candidate in store.list_factor_factory_candidates(run["id"]):
            key = (candidate["factor_key"], candidate["factor_version"])
            run_links.setdefault(key, []).append((run, candidate))

    experiment_summaries = store.list_factor_experiments(limit=10_000)
    experiments_by_definition: dict[str, list[dict[str, Any]]] = {}
    for summary in experiment_summaries:
        experiment = store.get_factor_experiment(summary["id"])
        if experiment is not None:
            experiments_by_definition.setdefault(experiment["factor_definition_id"], []).append(
                experiment
            )

    archives: list[dict[str, Any]] = []
    run_materials: dict[str, dict[str, Any]] = {}
    for definition in store.list_factor_definitions():
        key = (definition["key"], definition["version"])
        linked_runs = run_links.get(key, [])
        if definition.get("family") != "factor_factory" and not linked_runs:
            continue

        lifecycle_events = store.list_factor_lifecycle_events(
            definition["id"], target_market=definition["market"]
        )
        current = lifecycle_events[-1] if lifecycle_events else None
        current_state = str(current["state"] if current else "draft")
        if lifecycle_state and current_state != lifecycle_state:
            continue

        run_evidence = []
        for run, candidate in linked_runs:
            material = run_materials.get(run["id"])
            if material is None:
                evidence = _archive_run_evidence(run, candidate)
                material = {
                    "observation_summary": evidence["observation_summary"],
                    "simulation_orders": evidence["simulation_orders"],
                }
                run_materials[run["id"]] = material
            else:
                evidence = _archive_run_evidence(run, candidate, material)
            run_evidence.append(evidence)
        experiments = sorted(
            experiments_by_definition.get(definition["id"], []),
            key=lambda item: (item["created_at"], item["id"]),
        )
        latest_run = run_evidence[0] if run_evidence else None
        data_hashes = sorted(
            {
                str(item.get("data_provenance", {}).get("fingerprint"))
                for item in run_evidence
                if item.get("data_provenance", {}).get("fingerprint")
            }
        )
        archive_gate = _archive_admission_gate(run_evidence, lifecycle_events)
        archives.append(
            {
                "archive_id": definition["id"],
                "definition": definition,
                "verified": archive_gate["eligible"],
                "eligible_for_archive": archive_gate["eligible"],
                "archive_gate": archive_gate,
                "lifecycle": {
                    "current_state": current_state,
                    "current_event": current,
                    "events": lifecycle_events,
                },
                "scope": {
                    "market": definition["market"],
                    "symbol": latest_run.get("scope", {}).get("symbol") if latest_run else None,
                    "interval": (
                        latest_run.get("scope", {}).get("interval")
                        if latest_run
                        else definition.get("parameters", {}).get("interval")
                    ),
                    "horizon": definition["horizon"],
                    "data_source": latest_run.get("scope", {}).get("source")
                    if latest_run
                    else None,
                },
                "preregistration": {
                    "definition_hypothesis": definition.get("rationale") or "",
                    "invalidation_condition": definition.get("parameters", {}).get(
                        "invalidation_condition"
                    ),
                    "experiments": [_archive_preregistration(item) for item in experiments],
                },
                "post_study_evidence": {
                    "decision": {
                        "state": current_state,
                        "rule": current.get("rule") if current else "definition_registered",
                        "evidence": current.get("evidence") if current else {},
                        "created_at": current.get("created_at")
                        if current
                        else definition["created_at"],
                    },
                    "experiments": [_archive_post_study_experiment(item) for item in experiments],
                    "runs": run_evidence,
                    "latest_run": latest_run,
                },
                "remaining_risks": _archive_remaining_risks(current_state, latest_run),
                "evidence_chain": {
                    "definition_id": definition["id"],
                    "definition_hash": definition["definition_hash"],
                    "formula_hash": definition["formula_hash"],
                    "lifecycle_event_ids": [item["id"] for item in lifecycle_events],
                    "experiment_ids": [item["id"] for item in experiments],
                    "experiment_event_ids": [
                        event["id"] for item in experiments for event in item.get("events", [])
                    ],
                    "run_ids": [item["run_id"] for item in run_evidence],
                    "data_snapshot_hashes": data_hashes,
                    "simulation_order_ids": [
                        order["id"] for item in run_evidence for order in item["simulation_orders"]
                    ],
                },
                "live_trading_enabled": False,
            }
        )

    archives.sort(
        key=lambda item: (
            item["post_study_evidence"]["latest_run"]["updated_at"]
            if item["post_study_evidence"]["latest_run"]
            else item["definition"]["created_at"],
            item["definition"]["key"],
        ),
        reverse=True,
    )
    eligible_archives = [item for item in archives if item["eligible_for_archive"]]
    visible_archives = eligible_archives if eligible_only else archives
    selected = visible_archives[:limit]
    return {
        "ok": True,
        "count": len(selected),
        "total": len(eligible_archives),
        "research_record_count": len(archives),
        "ineligible_count": len(archives) - len(eligible_archives),
        "verified_count": len(eligible_archives),
        "eligible_only": eligible_only,
        "archives": selected,
        "live_trading_enabled": False,
    }


def _paper_account_id(run_id: str) -> str:
    return f"factor-factory:{run_id}"


def _execute_isolated_paper_order(
    *,
    run_id: str,
    symbol: str,
    market: str,
    factor_key: str,
    factor_version: str,
    market_time: str,
    price: float,
    quantity_delta: float,
    position_weight: float,
    commission_bps: float,
) -> dict[str, Any] | None:
    quantity = abs(float(quantity_delta))
    if quantity <= 1e-12:
        return None
    timestamp = datetime.fromisoformat(market_time)
    side = "buy" if quantity_delta > 0 else "sell"
    cycle_id = f"{run_id}:{market_time}"
    created = simulation_service.create_order(
        SimulationOrderCreate(
            symbol=symbol,
            market=market,
            side=side,
            order_type="market",
            quantity=quantity,
            account_id=_paper_account_id(run_id),
            factor_key=factor_key,
            factor_version=factor_version,
            research_run_id=run_id,
            rebalance_cycle_id=cycle_id,
            signal_time=timestamp,
            tradable_time=timestamp,
            theoretical_price=price,
            capacity_used=position_weight,
        )
    )
    filled = simulation_service.fill_isolated_order(
        created["id"],
        SimulationFillCreate(
            quantity=quantity,
            price=price,
            fee_rate=commission_bps / 10_000,
        ),
    )
    execution = filled["executions"][-1]
    return {
        "account_id": filled["account_id"],
        "simulation_order_id": filled["id"],
        "simulation_execution_id": execution["id"],
        "side": side,
        "quantity": quantity,
        "fee": execution["fee"],
        "fill_rate": filled["filled_quantity"] / filled["quantity"],
        "ledger_sync_status": execution["ledger_sync_status"],
        "rebalance_cycle_id": cycle_id,
    }


def start_factor_factory(req: FactorFactoryStartRequest) -> dict[str, Any]:
    with _discovery_lock:
        return _start_factor_factory_locked(req)


def _start_factor_factory_locked(req: FactorFactoryStartRequest) -> dict[str, Any]:
    frame, provenance = _load_frame(req)
    generation_fingerprint = _candidate_generation_fingerprint(
        req,
        data_fingerprint=provenance["fingerprint"],
    )
    existing = next(
        (
            run
            for run in store.list_factor_factory_runs(limit=10_000)
            if run["config"].get("candidate_generation_fingerprint") == generation_fingerprint
        ),
        None,
    )
    if existing is not None:
        replay = _detail(existing)
        replay["idempotent_replay"] = True
        return replay
    partitions = _split_frame(frame)
    split = _partition_contract(partitions)
    run_id = uuid.uuid4().hex
    plan_id = f"ff_{run_id[:20]}"
    specs, candidate_generation = _candidate_specs_for_request(
        run_id,
        req,
        generation_fingerprint=generation_fingerprint,
        discovery=partitions["discovery"],
    )
    candidate_universe_hash = _candidate_universe_hash(specs)
    research_fingerprint = _research_fingerprint(
        req,
        data_fingerprint=provenance["fingerprint"],
        candidate_universe_hash=candidate_universe_hash,
    )
    plan_response = create_factor_research_plan_record(
        FactorResearchPlanCreate(
            id=plan_id,
            title=f"自动因子研究 {req.symbol} {req.interval}",
            target_market=req.market,
            maximum_candidates=(
                req.candidate_budget
                + (
                    min(req.candidate_budget, req.ai_candidate_count)
                    if req.candidate_mode == "brain" and req.use_ai
                    else 0
                )
                + 1
            ),
            maximum_compute_units=(
                (req.candidate_budget + 1) * req.n_bars * 10
                + int(
                    candidate_generation.get("stages", {})
                    .get("grammar_generation", {})
                    .get("estimated_compute_units", 0)
                )
            ),
            maximum_llm_tokens=(
                req.maximum_ai_tokens if req.candidate_mode == "brain" and req.use_ai else 0
            ),
            maximum_confirmation_set_openings=1,
            maximum_round_candidates=req.candidate_budget,
            maximum_formula_complexity=30,
            maximum_duplicate_rate=0.35,
            stop_conditions={
                "stop_when_no_preliminary_candidate": True,
                "single_locked_confirmation_opening": True,
                "maximum_rounds": 1,
            },
            data_split=split,
        )
    )
    if not plan_response.get("ok"):
        raise ValueError(plan_response.get("error") or "自动研究计划创建失败")
    _record_ai_search_round(plan_id, specs, candidate_generation)
    config = req.model_dump(mode="json")
    config.update(
        {
            "market": req.market,
            "research_plan_id": plan_id,
            "data_provenance": provenance,
            "data_split": split.model_dump(mode="json"),
            "research_version": FACTOR_FACTORY_RESEARCH_VERSION,
            "candidate_universe_hash": candidate_universe_hash,
            "candidate_generation_fingerprint": generation_fingerprint,
            "candidate_generation": candidate_generation,
            "research_fingerprint": research_fingerprint,
            "live_trading_enabled": False,
        }
    )
    store.create_factor_factory_run(
        run_id,
        research_plan_id=plan_id,
        status="discovering",
        config=config,
    )
    try:
        result = _run_research(
            run_id,
            req,
            frame,
            partitions,
            provenance,
            specs,
            candidate_generation,
        )
    except Exception as exc:
        logger.exception("自动因子研究失败: %s", run_id)
        store.update_factor_factory_run(
            run_id,
            status="failed",
            result={"stage": "research", "live_trading_enabled": False},
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    return result


def _run_research(
    run_id: str,
    req: FactorFactoryStartRequest,
    frame: pd.DataFrame,
    partitions: dict[str, pd.DataFrame],
    provenance: dict[str, Any],
    specs: list[CandidateSpec],
    candidate_generation: dict[str, Any],
) -> dict[str, Any]:
    full_hash = market_data_module.fingerprint_frame(frame)
    validation_end = partitions["rolling_validation"]["datetime"].iloc[-1]
    discovery_start = partitions["discovery"]["datetime"].iloc[0]
    accepted_specs, rejected_specs, candidate_preflight = _candidate_preflight(
        specs,
        partitions["discovery"],
        budget=req.candidate_budget,
    )
    for spec in specs:
        rejection = rejected_specs.get(spec.key)
        if rejection is None:
            continue
        store.upsert_factor_factory_candidate(
            run_id=run_id,
            factor_key=spec.key,
            factor_version="1.0.0",
            source=spec.source,
            status="preflight_rejected",
            metrics={"preflight": rejection},
            gate={
                "passed": False,
                "stage": "candidate_preflight",
                **rejection,
            },
        )
    candidate_rows: list[dict[str, Any]] = []
    for spec in accepted_specs:
        try:
            definition = _register_candidate(spec, req)
            validation_response = validate_factor_candidate_data(
                FactorCandidateValidationRequest(
                    factor_key=definition["key"],
                    factor_version=definition["version"],
                    rows=_records(frame),
                    minimum_data_coverage=0.6,
                )
            )
            if not validation_response.get("ok"):
                raise ValueError(validation_response.get("error") or "候选数据校验失败")
            validation = validation_response["validation"]
            experiment_response = create_factor_experiment_record(
                FactorExperimentCreate(
                    research_plan_id=f"ff_{run_id[:20]}",
                    hypothesis=spec.hypothesis,
                    source=spec.source,
                    factor_key=definition["key"],
                    factor_version=definition["version"],
                    candidate_validation_id=validation["id"],
                    target_market=req.market,
                    data_start=discovery_start.date(),
                    data_end=validation_end.date(),
                    estimated_compute_units=len(frame),
                    model=spec.model,
                    prompt=spec.prompt,
                    applicable_regimes=["trend", "range", "high_volatility", "low_volatility"],
                    invalidation_conditions=[spec.invalidation],
                    falsification_tests=list(spec.falsification_tests),
                    ai_trace=spec.ai_trace,
                    pre_registration=FactorPreRegistration(
                        primary_metric="rolling_validation_after_cost_return",
                        secondary_metrics=["sharpe", "max_drawdown", "rank_ic", "p_value"],
                        pass_criteria=req.thresholds.model_dump(mode="json"),
                        maximum_candidates=1,
                        confirmation_set_openings=0,
                    ),
                )
            )
            if not experiment_response.get("ok"):
                raise ValueError(experiment_response.get("error") or "候选实验创建失败")
            experiment = experiment_response["experiment"]
            _experiment_event(experiment["id"], "queued")
            _experiment_event(experiment["id"], "running")

            raw_signal = evaluate_factor_ast(definition["ast"], frame)
            signal = pd.Series(np.tanh(raw_signal.astype(float) / 2), index=frame.index)
            signal_by_time = pd.Series(signal.to_numpy(), index=frame["datetime"])
            metrics: dict[str, Any] = {}
            for partition_name in ("discovery", "rolling_validation"):
                partition = partitions[partition_name]
                partition_signal = signal_by_time.reindex(partition["datetime"]).reset_index(
                    drop=True
                )
                metrics[partition_name] = _backtest_partition(
                    partition,
                    partition_signal,
                    req=req,
                )
            validation_partition = partitions["rolling_validation"]
            validation_signal = signal_by_time.reindex(
                validation_partition["datetime"]
            ).reset_index(drop=True)
            metrics["rolling_validation_cost_stress"] = _backtest_partition(
                validation_partition,
                validation_signal,
                req=req,
                commission_bps=min(200.0, req.commission_bps * 2),
            )
            gate = _preliminary_gate(metrics, req)
            score = _score(metrics)
            validation_summary = metrics["rolling_validation"]["summary"]
            experiment = _experiment_event(
                experiment["id"],
                "succeeded",
                result={
                    "candidate_results": [
                        {
                            "factor_key": definition["key"],
                            "raw_p_value": validation_summary["raw_p_value"],
                            "effective_sample_size": validation_summary["effective_sample_size"],
                            "preliminary_gate_passed": gate["passed"],
                            "metrics": metrics,
                        }
                    ]
                },
                evidence={
                    "data_snapshot_hash": full_hash,
                    "confirmation_labels_accessed": False,
                    "live_trading_enabled": False,
                },
            )
            current = store.ensure_factor_lifecycle_draft(definition["id"], req.market)
            if current and current["state"] == "draft":
                transition = transition_factor_lifecycle(
                    definition["key"],
                    definition["version"],
                    FactorLifecycleTransitionRequest(
                        state="exploratory",
                        target_market=req.market,
                        actor_type="system",
                        actor="factor-factory",
                        rule="coverage_validated",
                        evidence={
                            **_base_lifecycle_evidence(
                                definition,
                                data_hash=full_hash,
                                attempts=experiment["attempt_number"],
                                start=discovery_start.isoformat(),
                                end=validation_end.isoformat(),
                                req=req,
                            ),
                            "candidate_validation_id": validation["id"],
                            "experiment_ids": [experiment["id"]],
                            "preliminary_gate": gate,
                        },
                    ),
                )
                if not transition.get("ok"):
                    raise ValueError(transition.get("error") or "候选生命周期晋级失败")
            candidate = {
                "spec": spec,
                "definition": definition,
                "validation": validation,
                "experiment": experiment,
                "signal": signal,
                "metrics": metrics,
                "gate": gate,
                "score": score,
            }
            candidate_rows.append(candidate)
            store.upsert_factor_factory_candidate(
                run_id=run_id,
                factor_key=definition["key"],
                factor_version=definition["version"],
                source=spec.source,
                experiment_id=experiment["id"],
                status="preliminary_passed" if gate["passed"] else "gate_rejected",
                metrics={**metrics, "score": score},
                gate=gate,
            )
        except (FactorDslError, KeyError, TypeError, ValueError) as exc:
            logger.warning("自动候选 %s 被拒绝: %s", spec.key, exc)
            store.upsert_factor_factory_candidate(
                run_id=run_id,
                factor_key=spec.key,
                factor_version="1.0.0",
                source=spec.source,
                status="invalid",
                metrics={},
                gate={"passed": False, "error": str(exc)},
            )

    ranked = sorted(candidate_rows, key=lambda item: item["score"], reverse=True)
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
        definition = item["definition"]
        store.upsert_factor_factory_candidate(
            run_id=run_id,
            factor_key=definition["key"],
            factor_version=definition["version"],
            source=item["spec"].source,
            experiment_id=item["experiment"]["id"],
            status="preliminary_passed" if item["gate"]["passed"] else "gate_rejected",
            rank=rank,
            metrics={**item["metrics"], "score": item["score"]},
            gate=item["gate"],
        )
    eligible = [item for item in ranked if item["gate"]["passed"]]
    direction_radar = _direction_radar(ranked)
    if not eligible:
        saved = store.update_factor_factory_run(
            run_id,
            status="no_qualified_factor",
            result={
                "message": "没有候选通过滚动验证门禁，未开启锁定确认集或模拟盘。",
                "candidate_count": len(specs),
                "valid_candidate_count": len(candidate_rows),
                "candidate_preflight": candidate_preflight,
                "candidate_generation": candidate_generation,
                "direction_radar": direction_radar,
                "data_provenance": provenance,
                "live_trading_enabled": False,
            },
        )
        return _detail(saved)

    winner = eligible[0]
    definition = winner["definition"]
    confirmation_experiment_response = create_factor_experiment_record(
        FactorExperimentCreate(
            research_plan_id=f"ff_{run_id[:20]}",
            hypothesis=f"锁定 {definition['key']} 并只开启一次最终确认集。",
            source="parameter_search",
            parent_experiment_id=winner["experiment"]["id"],
            factor_key=definition["key"],
            factor_version=definition["version"],
            candidate_validation_id=winner["validation"]["id"],
            target_market=req.market,
            data_start=discovery_start.date(),
            data_end=validation_end.date(),
            estimated_compute_units=len(partitions["rolling_validation"]),
            applicable_regimes=["locked_formula"],
            invalidation_conditions=[winner["spec"].invalidation],
            falsification_tests=["单次锁定确认集", "高低波动状态分组"],
            pre_registration=FactorPreRegistration(
                primary_metric="locked_confirmation_after_cost_return",
                secondary_metrics=["incremental_return", "sharpe", "max_drawdown", "p_value"],
                pass_criteria=req.thresholds.model_dump(mode="json"),
                maximum_candidates=1,
                confirmation_set_openings=1,
            ),
        )
    )
    if not confirmation_experiment_response.get("ok"):
        raise ValueError(confirmation_experiment_response.get("error") or "确认实验创建失败")
    confirmation_experiment = confirmation_experiment_response["experiment"]
    _experiment_event(confirmation_experiment["id"], "queued")
    _experiment_event(confirmation_experiment["id"], "running")
    validation_summary = winner["metrics"]["rolling_validation"]["summary"]
    confirmation_experiment = _experiment_event(
        confirmation_experiment["id"],
        "succeeded",
        result={
            "candidate_results": [
                {
                    "factor_key": definition["key"],
                    "raw_p_value": validation_summary["raw_p_value"],
                    "effective_sample_size": validation_summary["effective_sample_size"],
                    "locked_formula": True,
                }
            ]
        },
        evidence={"confirmation_labels_accessed": False, "formula_locked": True},
    )
    opening = open_factor_confirmation_set(
        f"ff_{run_id[:20]}",
        FactorConfirmationSetOpenRequest(
            experiment_id=confirmation_experiment["id"],
            confirmation_data_fingerprint=market_data_module.fingerprint_frame(
                partitions["locked_confirmation"]
            ),
            opened_by="factor-factory",
            irreversible_ack=True,
        ),
    )
    if not opening.get("ok"):
        raise ValueError(opening.get("error") or "锁定确认集开启失败")

    confirmation = partitions["locked_confirmation"]
    signal_by_time = pd.Series(winner["signal"].to_numpy(), index=frame["datetime"])
    confirmation_signal = signal_by_time.reindex(confirmation["datetime"]).reset_index(drop=True)
    confirmation_metrics = _backtest_partition(confirmation, confirmation_signal, req=req)
    benchmark_metrics = _backtest_partition(
        confirmation,
        pd.Series(1.0, index=range(len(confirmation))),
        req=req,
    )
    regime = _regime_stability(
        confirmation.reset_index(drop=True),
        confirmation_signal,
        req.commission_bps / 10_000,
    )
    selected_validation_return = float(
        winner["metrics"]["rolling_validation"]["summary"]["total_return"]
    )
    family_passes = sum(
        item["definition"]["family"] == definition["family"]
        and float(item["metrics"]["rolling_validation"]["summary"]["total_return"])
        >= req.thresholds.minimum_validation_return
        and abs(float(item["metrics"]["rolling_validation"]["summary"]["max_drawdown"]))
        <= req.thresholds.maximum_drawdown
        and float(item["metrics"]["rolling_validation"]["summary"]["total_return"])
        * selected_validation_return
        >= 0
        for item in candidate_rows
    )
    summary = confirmation_metrics["summary"]
    incremental_return = float(summary["total_return"]) - float(
        benchmark_metrics["summary"]["total_return"]
    )
    period_returns = [
        winner["metrics"]["discovery"]["summary"]["total_return"],
        winner["metrics"]["rolling_validation"]["summary"]["total_return"],
        summary["total_return"],
    ]
    thresholds = req.thresholds
    confirmation_checks = {
        "confirmation_return": summary["total_return"] >= thresholds.minimum_confirmation_return,
        "incremental_return": incremental_return >= thresholds.minimum_incremental_return,
        "confirmation_drawdown": abs(summary["max_drawdown"]) <= thresholds.maximum_drawdown,
        "confirmation_sharpe": float(summary["metrics"].get("sharpe") or 0)
        >= thresholds.minimum_confirmation_sharpe,
        "minimum_trades": int(summary["n_trades"]) >= thresholds.minimum_trades,
        "p_value": float(summary["raw_p_value"]) <= thresholds.maximum_p_value,
        "window_majority": sum(value >= 0 for value in period_returns) >= 2,
        "parameter_plateau": family_passes >= 2,
        "regime_stability": regime["passed"],
    }
    confirmation_gate = {
        "passed": all(confirmation_checks.values()),
        "checks": confirmation_checks,
        "incremental_return": incremental_return,
        "period_returns": period_returns,
        "regime_stability": regime,
    }
    store.upsert_factor_factory_candidate(
        run_id=run_id,
        factor_key=definition["key"],
        factor_version=definition["version"],
        source=winner["spec"].source,
        experiment_id=confirmation_experiment["id"],
        status="research_passed" if confirmation_gate["passed"] else "confirmation_rejected",
        rank=int(winner["rank"]),
        metrics={
            **winner["metrics"],
            "locked_confirmation": confirmation_metrics,
            "buy_hold_confirmation": benchmark_metrics,
            "score": winner["score"],
        },
        gate=confirmation_gate,
    )
    if not confirmation_gate["passed"]:
        saved = store.update_factor_factory_run(
            run_id,
            status="no_research_passed_factor",
            selected_factor_key=definition["key"],
            selected_factor_version=definition["version"],
            selected_experiment_id=confirmation_experiment["id"],
            result={
                "message": "最优候选未通过锁定确认门禁，未进入模拟盘。",
                "confirmation_gate": confirmation_gate,
                "confirmation_opening": opening["opening"],
                "candidate_preflight": candidate_preflight,
                "candidate_generation": candidate_generation,
                "direction_radar": direction_radar,
                "data_provenance": provenance,
                "live_trading_enabled": False,
            },
        )
        return _detail(saved)

    lifecycle_evidence = {
        **_base_lifecycle_evidence(
            definition,
            data_hash=full_hash,
            attempts=confirmation_experiment["attempt_number"],
            start=discovery_start.isoformat(),
            end=confirmation["datetime"].iloc[-1].isoformat(),
            req=req,
        ),
        "locked_out_of_sample": True,
        "statistical_gate_passed": True,
        "ai_accessed_locked_labels": False,
        "window_majority_passed": confirmation_checks["window_majority"],
        "group_stability_passed": confirmation_checks["regime_stability"],
        "parameter_plateau_passed": confirmation_checks["parameter_plateau"],
        "research_plan_id": f"ff_{run_id[:20]}",
        "experiment_ids": [confirmation_experiment["id"]],
        "confirmation_set_opening_id": opening["opening"]["id"],
        "confirmation_gate": confirmation_gate,
        "incremental_value_passed": confirmation_checks["incremental_return"],
    }
    lifecycle = transition_factor_lifecycle(
        definition["key"],
        definition["version"],
        FactorLifecycleTransitionRequest(
            state="research_passed",
            target_market=req.market,
            actor_type="system",
            actor="factor-factory",
            rule="locked_out_of_sample_statistical_gate",
            evidence=lifecycle_evidence,
        ),
    )
    if not lifecycle.get("ok"):
        raise ValueError(lifecycle.get("error") or "研究通过状态写入失败")

    now = time.time()
    observation_ends_at = now + req.observation_days * 86_400
    latest_signal = float(
        pd.Series(winner["signal"]).replace([np.inf, -np.inf], np.nan).fillna(0).iloc[-1]
    )
    position_weight = max(0.0, min(1.0, latest_signal))
    latest_price = float(frame["close"].iloc[-1])
    market_time = frame["datetime"].iloc[-1].isoformat()
    position_quantity = req.initial_capital * position_weight / latest_price
    paper_order = _execute_isolated_paper_order(
        run_id=run_id,
        symbol=req.symbol,
        market=req.market,
        factor_key=definition["key"],
        factor_version=definition["version"],
        market_time=market_time,
        price=latest_price,
        quantity_delta=position_quantity,
        position_weight=position_weight,
        commission_bps=req.commission_bps,
    )
    entry_cost = float(paper_order["fee"]) / req.initial_capital if paper_order is not None else 0.0
    initial_equity = req.initial_capital * (1 - entry_cost)
    execution_record = {
        "signal_time": market_time,
        "tradable_time": market_time,
        "theoretical_price": latest_price,
        "simulated_price": latest_price,
        "slippage_bps": 0.0,
        "rejection_reason": None,
        "capacity_used": position_weight,
        "simulation_order_id": paper_order["simulation_order_id"] if paper_order else None,
        "simulation_execution_id": (
            paper_order["simulation_execution_id"] if paper_order else None
        ),
        "fee": paper_order["fee"] if paper_order else 0.0,
    }
    demo_package: StrategyReleasePackage | None = None
    demo_activation: dict[str, Any] | None = None
    if req.paper_target == "okx_demo":
        demo_package = build_demo_release_package(
            run_id=run_id,
            research_plan_id=f"ff_{run_id[:20]}",
            experiment_id=confirmation_experiment["id"],
            definition=definition,
            confirmation_summary=confirmation_metrics["summary"],
            data_fingerprint=full_hash,
            req=req,
        )
        try:
            demo_activation = activate_demo_strategy(
                package=demo_package,
                run_id=run_id,
                market_time=market_time,
                signal=position_weight,
                price=latest_price,
            )
        except Exception as exc:  # noqa: BLE001 - Runner 失败不得抹掉研究证据
            logger.warning("OKX Demo 自动激活被阻止 run=%s: %s", run_id, exc)
            demo_activation = {
                "status": "blocked",
                "error": trading_errors.redact(f"{type(exc).__name__}: {exc}"),
                "live_trading_enabled": False,
            }
        execution_record["okx_demo_order_id"] = (
            (demo_activation.get("order") or {}).get("order_id") if demo_activation else None
        )
    store.append_factor_factory_observation(
        run_id,
        market_time=market_time,
        price=latest_price,
        signal=latest_signal,
        position_weight=position_weight,
        gross_return=0.0,
        cost=entry_cost,
        net_return=-entry_cost,
        equity=initial_equity,
        drawdown=0.0,
        fill_rate=1.0,
        payload={
            "kind": "paper_entry",
            "paper_position_quantity": position_quantity,
            "simulation_order": paper_order,
            "okx_demo": demo_activation,
            "execution": execution_record,
        },
    )
    saved = store.update_factor_factory_run(
        run_id,
        status="paper_observing",
        selected_factor_key=definition["key"],
        selected_factor_version=definition["version"],
        selected_experiment_id=confirmation_experiment["id"],
        observation_started_at=now,
        observation_ends_at=observation_ends_at,
        result={
            "message": "因子通过锁定确认门禁，已进入前向内部模拟观察。",
            "research_lifecycle_event": lifecycle["event"],
            "confirmation_gate": confirmation_gate,
            "confirmation_opening": opening["opening"],
            "candidate_preflight": candidate_preflight,
            "candidate_generation": candidate_generation,
            "direction_radar": direction_radar,
            "research_metrics": confirmation_metrics["summary"],
            "reference_factor_values": [
                float(value)
                for value in confirmation_signal.replace([np.inf, -np.inf], np.nan)
                .dropna()
                .tail(200)
            ],
            "reference_ic": summary["rank_ic"],
            "paper": {
                "mode": (
                    "okx_demo_with_internal_mirror"
                    if req.paper_target == "okx_demo"
                    else "forward_simulation_account"
                ),
                "target": req.paper_target,
                "account_id": _paper_account_id(run_id),
                "started_at": datetime.fromtimestamp(now, UTC).isoformat(),
                "ends_at": datetime.fromtimestamp(observation_ends_at, UTC).isoformat(),
                "completed_rebalance_cycles": 1,
                "execution_records": [execution_record],
                "simulation_order_ids": (
                    [paper_order["simulation_order_id"]] if paper_order else []
                ),
                "current_position_quantity": position_quantity,
                "shared_ledger_mutated": False,
                "okx_demo": (
                    {
                        "strategy_package": demo_package.model_dump(mode="json"),
                        "latest_activation": demo_activation,
                        "activation_history": [demo_activation],
                        "target_quantity": (
                            demo_activation.get("target_quantity", 0.0) if demo_activation else 0.0
                        ),
                    }
                    if demo_package is not None
                    else None
                ),
                "live_trading_enabled": False,
            },
            "data_provenance": provenance,
            "live_trading_enabled": False,
        },
    )
    return _detail(saved)


def get_factor_factory_run(run_id: str) -> dict[str, Any] | None:
    run = store.get_factor_factory_run(run_id)
    return _detail(run) if run else None


def list_factor_factory_runs(
    *,
    status: str | None = None,
    market: str | None = None,
    symbol: str | None = None,
    interval: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    runs = store.list_factor_factory_runs(status=status, limit=10_000)
    normalized_symbol = symbol.strip().upper() if symbol else None
    runs = [
        run
        for run in runs
        if (market is None or run["config"].get("market") == market)
        and (
            normalized_symbol is None
            or str(run["config"].get("symbol") or "").upper() == normalized_symbol
        )
        and (interval is None or run["config"].get("interval") == interval)
    ][:limit]
    return {
        "ok": True,
        "count": len(runs),
        "runs": [
            {
                **run,
                "candidate_count": len(store.list_factor_factory_candidates(run["id"])),
                "observation_count": len(store.list_factor_factory_observations(run["id"])),
            }
            for run in runs
        ],
        "live_trading_enabled": False,
    }


def _current_observation_ic(observations: list[dict[str, Any]]) -> float:
    if len(observations) < 3:
        return 0.0
    signals = pd.Series([item["signal"] for item in observations[:-1]], dtype=float)
    prices = pd.Series([item["price"] for item in observations], dtype=float)
    forward_returns = prices.pct_change().iloc[1:].reset_index(drop=True)
    return _spearman(signals.reset_index(drop=True), forward_returns)


def _monitor_drift(
    run: dict[str, Any],
    observations: list[dict[str, Any]],
    req: FactorFactoryStartRequest,
) -> dict[str, Any] | None:
    reference = [float(item) for item in run["result"].get("reference_factor_values", [])]
    current = [float(item["signal"]) for item in observations]
    if len(reference) < 20 or len(current) < 20:
        return None
    return factor_drift_report(
        reference_values=reference,
        current_values=current,
        reference_ic=float(run["result"].get("reference_ic", 0.0)),
        current_ic=_current_observation_ic(observations),
        reference_coverage=1.0,
        current_coverage=sum(math.isfinite(item) for item in current) / len(current),
        current_cost_bps=req.commission_bps,
        current_capacity_ratio=max(
            0.0, 1.0 - max(item["position_weight"] for item in observations)
        ),
        reference_correlated_factors={},
        current_correlated_factors={},
        thresholds={
            "maximum_ic_decay": 0.6,
            "maximum_coverage_drop": 0.2,
            "maximum_psi": 0.35,
            "maximum_distribution_distance": 1.0,
            "maximum_correlation_shift": 0.35,
            "maximum_cost_bps": max(20.0, req.commission_bps * 3),
            "minimum_capacity_ratio": req.thresholds.minimum_capacity_ratio,
        },
        affected_strategies=[
            {
                "strategy_id": f"factor-factory:{run['id']}",
                "factor_keys": [run["selected_factor_key"]],
                "active": True,
            }
        ],
        factor_key=str(run["selected_factor_key"]),
    )


def _degrade_for_drift(
    run: dict[str, Any],
    req: FactorFactoryStartRequest,
    monitoring: dict[str, Any],
) -> bool:
    if not monitoring.get("alerts"):
        return False
    definition = store.get_factor_definition(
        str(run["selected_factor_key"]), str(run["selected_factor_version"])
    )
    if definition is None:
        return False
    current = store.get_latest_factor_lifecycle_event(definition["id"], req.market)
    if current is None or current["state"] not in {"research_passed", "trading_validated"}:
        return current is not None and current["state"] == "degraded"
    experiment = store.get_factor_experiment(str(run["selected_experiment_id"]))
    config = run["config"]
    evidence = _base_lifecycle_evidence(
        definition,
        data_hash=str(config["data_provenance"]["fingerprint"]),
        attempts=int(experiment["attempt_number"]) if experiment else 1,
        start=str(config["data_split"]["discovery"]["start"]),
        end=str(config["data_split"]["locked_confirmation"]["end"]),
        req=req,
    )
    transition = transition_factor_lifecycle(
        definition["key"],
        definition["version"],
        FactorLifecycleTransitionRequest(
            state="degraded",
            target_market=req.market,
            actor_type="system",
            actor="factor-factory-monitor",
            rule="monitoring_gate_failed",
            evidence={
                **evidence,
                "degradation_reason": ",".join(monitoring["alerts"]),
                "monitoring": monitoring,
                "simulation_run_id": run["id"],
            },
        ),
    )
    return bool(transition.get("ok"))


def _simulation_gap_attribution(
    run: dict[str, Any],
    observations: list[dict[str, Any]],
    req: FactorFactoryStartRequest,
) -> dict[str, Any]:
    research = dict(run["result"].get("research_metrics", {}))
    research_return = float(research.get("total_return") or 0.0)
    simulation_return = observations[-1]["equity"] / req.initial_capital - 1
    positions = [float(item["position_weight"]) for item in observations]
    turnover = sum(abs(current - previous) for previous, current in pairwise(positions))
    simulation_cost = sum(float(item["cost"]) for item in observations)
    execution_records = list(run["result"].get("paper", {}).get("execution_records", []))
    execution_drag = -sum(
        abs(float(item.get("capacity_used") or 0.0))
        * abs(float(item.get("slippage_bps") or 0.0))
        / 10_000
        for item in execution_records
    )
    cost_drag = -simulation_cost
    data_delay_drag = 0.0
    portfolio_constraint_drag = 0.0
    total_gap = simulation_return - research_return
    signal_decay = total_gap - (
        execution_drag + cost_drag + data_delay_drag + portfolio_constraint_drag
    )
    observation_count = max(1, len(observations))
    effective_sample_size = max(1, int(research.get("effective_sample_size") or 1))
    actual_cost_bps = simulation_cost * 10_000 / max(turnover, 1e-12) if turnover else 0.0
    report = research_simulation_gap_attribution(
        research_returns=[research_return],
        simulation_returns=[simulation_return],
        signal_decay=[signal_decay],
        data_delay=[data_delay_drag],
        execution=[execution_drag],
        costs=[cost_drag],
        portfolio_constraints=[portfolio_constraint_drag],
        research_metrics={
            "ic": float(research.get("rank_ic") or 0.0),
            "coverage": 1.0,
            "turnover": float(research.get("n_trades") or 0) / effective_sample_size,
            "cost_bps": req.commission_bps,
            "fill_rate": 1.0,
        },
        simulation_metrics={
            "ic": _current_observation_ic(observations),
            "coverage": sum(math.isfinite(item["signal"]) for item in observations)
            / observation_count,
            "turnover": turnover / observation_count,
            "cost_bps": actual_cost_bps,
            "fill_rate": min(float(item["fill_rate"]) for item in observations),
        },
    )
    report["methodology"] = {
        "scope": "aggregate_research_confirmation_vs_forward_simulation",
        "signal_decay_is_residual": True,
        "data_delay_assumption": "bar_close_signal_and_same_bar_simulated_fill",
        "portfolio_constraint_assumption": "same_long_only_mapping_in_research_and_simulation",
        "shared_ledger_mutated": False,
    }
    return report


def _finalize_paper_if_due(
    run: dict[str, Any],
    observations: list[dict[str, Any]],
    req: FactorFactoryStartRequest,
    monitoring: dict[str, Any] | None,
) -> tuple[str, dict[str, Any] | None]:
    observation_ends_at = run["observation_ends_at"]
    if observation_ends_at is None or time.time() < float(observation_ends_at):
        return run["status"], None
    observation_started_at = run.get("observation_started_at")
    observed_seconds = (
        max(0.0, time.time() - float(observation_started_at))
        if observation_started_at is not None
        else 0.0
    )
    required_observation_days = max(ARCHIVE_MINIMUM_OBSERVATION_DAYS, req.observation_days)
    required_observation_seconds = required_observation_days * 86_400
    if observed_seconds < required_observation_seconds:
        return run["status"], {
            "eligible_for_trading_validated": False,
            "violations": ["observation_period_incomplete"],
            "required_observation_days": required_observation_days,
            "observed_seconds": observed_seconds,
            "observed_days": observed_seconds / 86_400,
            "live_trading_enabled": False,
        }
    if len(observations) < req.thresholds.minimum_observations:
        return run["status"], {
            "eligible_for_trading_validated": False,
            "violations": ["minimum_observations"],
            "observation_count": len(observations),
            "required_observations": req.thresholds.minimum_observations,
            "live_trading_enabled": False,
        }
    initial = float(run["config"]["initial_capital"])
    after_cost_return = observations[-1]["equity"] / initial - 1
    fill_rate = min(item["fill_rate"] for item in observations)
    capacity_ratio = max(0.0, 1.0 - max(item["position_weight"] for item in observations))
    paper = run["result"].get("paper", {})
    validation = simulation_validation_report(
        completed_rebalance_cycles=int(paper.get("completed_rebalance_cycles", 1)),
        after_cost_return=after_cost_return,
        fill_rate=fill_rate,
        capacity_ratio=capacity_ratio,
        thresholds={
            "minimum_after_cost_return": req.thresholds.minimum_paper_return,
            "minimum_fill_rate": req.thresholds.minimum_fill_rate,
            "minimum_capacity_ratio": req.thresholds.minimum_capacity_ratio,
        },
        execution_records=list(paper.get("execution_records", [])),
    )
    max_drawdown = abs(min(item["drawdown"] for item in observations))
    validation["checks"]["paper_drawdown"] = max_drawdown <= req.thresholds.maximum_paper_drawdown
    if not validation["checks"]["paper_drawdown"]:
        validation["violations"] = sorted([*validation["violations"], "paper_drawdown"])
        validation["eligible_for_trading_validated"] = False
    if monitoring and monitoring.get("alerts"):
        validation["violations"] = sorted([*validation["violations"], "drift_monitoring"])
        validation["eligible_for_trading_validated"] = False
    validation.update(
        {
            "observation_count": len(observations),
            "after_cost_return": after_cost_return,
            "maximum_drawdown": -max_drawdown,
            "observed_from": observations[0]["market_time"],
            "observed_to": observations[-1]["market_time"],
            "required_observation_days": required_observation_days,
            "observed_seconds": observed_seconds,
            "observed_days": observed_seconds / 86_400,
            "observation_period_completed": True,
            "research_simulation_gap_attribution": _simulation_gap_attribution(
                run, observations, req
            ),
        }
    )
    if req.paper_target == "okx_demo":
        demo_state = dict(paper.get("okx_demo") or {})
        demo_evidence = dict(demo_state.get("latest_evidence") or {})
        account = demo_evidence.get("account")
        activation_history = list(demo_state.get("activation_history", []))
        baseline_equity = next(
            (
                float(item["baseline_account_equity"])
                for item in activation_history
                if item and item.get("baseline_account_equity")
            ),
            None,
        )
        current_equity = (
            float(account["equity"])
            if isinstance(account, dict) and account.get("equity") is not None
            else None
        )
        demo_return = (
            current_equity / baseline_equity - 1
            if current_equity is not None and baseline_equity is not None and baseline_equity > 0
            else None
        )
        demo_drawdown = (
            abs(float(account.get("max_drawdown") or 0.0)) if isinstance(account, dict) else None
        )
        demo_orders = list(demo_evidence.get("orders") or [])
        funding = demo_evidence.get("funding_rate")
        funding_recorded = isinstance(funding, dict) and funding.get("funding_rate") is not None
        final_statuses = {"FILLED", "CANCELLED", "REJECTED"}
        demo_checks = {
            "okx_demo_order_recorded": bool(demo_orders),
            "okx_demo_order_lifecycle_final": bool(demo_orders)
            and all(str(item.get("status")) in final_statuses for item in demo_orders),
            "okx_demo_fill_rate": float(demo_evidence.get("fill_rate") or 0.0)
            >= req.thresholds.minimum_fill_rate,
            "okx_demo_reconciliation": demo_evidence.get("reconciliation_clear") is True,
            "okx_demo_risk_mode": demo_evidence.get("risk_mode_normal") is True,
            "okx_demo_account_return": demo_return is not None
            and demo_return >= req.thresholds.minimum_paper_return,
            "okx_demo_account_drawdown": demo_drawdown is not None
            and demo_drawdown <= req.thresholds.maximum_paper_drawdown,
            "okx_demo_funding_rate_recorded": funding_recorded,
        }
        validation["checks"].update(demo_checks)
        validation["violations"] = sorted(
            key for key, passed in validation["checks"].items() if not passed
        )
        validation["eligible_for_trading_validated"] = not validation["violations"]
        validation["okx_demo"] = {
            "strategy_id": demo_evidence.get("strategy_id"),
            "strategy_version": demo_evidence.get("strategy_version"),
            "order_count": len(demo_orders),
            "fill_count": int(demo_evidence.get("fill_count") or 0),
            "fill_rate": float(demo_evidence.get("fill_rate") or 0.0),
            "baseline_account_equity": baseline_equity,
            "current_account_equity": current_equity,
            "after_cost_account_return": demo_return,
            "maximum_account_drawdown": -demo_drawdown if demo_drawdown is not None else None,
            "funding_rate": funding,
            "reconciliation_clear": demo_evidence.get("reconciliation_clear"),
            "risk_mode_normal": demo_evidence.get("risk_mode_normal"),
            "evidence_scope": "okx_demo_account",
            "live_trading_enabled": False,
        }
        if demo_return is not None:
            validation["after_cost_return"] = demo_return
        if demo_drawdown is not None:
            validation["maximum_drawdown"] = -demo_drawdown
    if not validation["eligible_for_trading_validated"]:
        return "paper_rejected", validation

    definition = store.get_factor_definition(
        str(run["selected_factor_key"]), str(run["selected_factor_version"])
    )
    experiment = store.get_factor_experiment(str(run["selected_experiment_id"]))
    if definition is None or experiment is None:
        validation["eligible_for_trading_validated"] = False
        validation["violations"] = sorted([*validation["violations"], "missing_lineage"])
        return "paper_rejected", validation
    config = run["config"]
    transition = transition_factor_lifecycle(
        definition["key"],
        definition["version"],
        FactorLifecycleTransitionRequest(
            state="trading_validated",
            target_market=req.market,
            actor_type="system",
            actor="factor-factory-monitor",
            rule="target_market_trading_gate",
            evidence={
                **_base_lifecycle_evidence(
                    definition,
                    data_hash=str(config["data_provenance"]["fingerprint"]),
                    attempts=int(experiment["attempt_number"]),
                    start=str(config["data_split"]["discovery"]["start"]),
                    end=str(config["data_split"]["locked_confirmation"]["end"]),
                    req=req,
                ),
                "cost_passed": True,
                "capacity_passed": True,
                "execution_passed": True,
                "incremental_value_passed": True,
                "simulation_validation_passed": True,
                "after_cost_performance_passed": True,
                "fill_rate_passed": True,
                "simulation_run_id": run["id"],
                "observation_started_at": datetime.fromtimestamp(
                    float(observation_started_at), UTC
                ).isoformat(),
                "observation_ended_at": datetime.now(UTC).isoformat(),
                "observation_days_completed": observed_seconds / 86_400,
                "observation_period_completed": True,
                "completed_rebalance_cycles": validation["completed_rebalance_cycles"],
                "execution_record_count": validation["execution_record_count"],
                "simulation_validation": validation,
                "live_trading_enabled": False,
            },
        ),
    )
    if not transition.get("ok"):
        validation["eligible_for_trading_validated"] = False
        validation["violations"] = sorted([*validation["violations"], "lifecycle_transition"])
        validation["lifecycle_error"] = transition.get("error")
        return "paper_rejected", validation
    validation["lifecycle_event"] = transition["event"]
    return "trading_validated", validation


def observe_factor_factory(
    run_id: str,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    with _observe_lock:
        return _observe_factor_factory_locked(run_id, force_refresh=force_refresh)


def _observe_factor_factory_locked(
    run_id: str,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    run = store.get_factor_factory_run(run_id)
    if run is None:
        raise KeyError("自动因子运行不存在")
    if run["status"] != "paper_observing":
        return _detail(run)
    req = FactorFactoryStartRequest.model_validate(run["config"])
    frame, provenance = _load_frame(req, force_refresh=force_refresh)
    definition = store.get_factor_definition(
        str(run["selected_factor_key"]), str(run["selected_factor_version"])
    )
    if definition is None:
        raise ValueError("模拟观察绑定的因子定义不存在")
    raw_signal = evaluate_factor_ast(definition["ast"], frame)
    signals = pd.Series(np.tanh(raw_signal.astype(float) / 2), index=frame.index)
    signal = float(signals.replace([np.inf, -np.inf], np.nan).fillna(0).iloc[-1])
    position_weight = max(0.0, min(1.0, signal))
    price = float(frame["close"].iloc[-1])
    market_time = frame["datetime"].iloc[-1].isoformat()
    prior = store.list_factor_factory_observations(run_id)
    previous = prior[-1]
    price_return = price / max(previous["price"], 1e-12) - 1
    gross_return = previous["position_weight"] * price_return
    previous_quantity = float(
        previous["payload"].get(
            "paper_position_quantity",
            previous["equity"] * previous["position_weight"] / max(previous["price"], 1e-12),
        )
    )
    pre_cost_equity = previous["equity"] * (1 + gross_return)
    position_quantity = pre_cost_equity * position_weight / max(price, 1e-12)
    quantity_delta = position_quantity - previous_quantity
    new_market_bar = all(item["market_time"] != market_time for item in prior)
    paper_order = (
        _execute_isolated_paper_order(
            run_id=run_id,
            symbol=req.symbol,
            market=req.market,
            factor_key=definition["key"],
            factor_version=definition["version"],
            market_time=market_time,
            price=price,
            quantity_delta=quantity_delta,
            position_weight=position_weight,
            commission_bps=req.commission_bps,
        )
        if new_market_bar
        else None
    )
    existing_paper = dict(run["result"].get("paper", {}))
    existing_demo = dict(existing_paper.get("okx_demo") or {})
    demo_activation: dict[str, Any] | None = None
    demo_evidence: dict[str, Any] | None = None
    if req.paper_target == "okx_demo" and existing_demo.get("strategy_package"):
        package = StrategyReleasePackage.model_validate(existing_demo["strategy_package"])
        previous_demo_status = str(
            (existing_demo.get("latest_activation") or {}).get("status") or ""
        )
        should_activate = new_market_bar or previous_demo_status == "blocked"
        if should_activate:
            try:
                demo_activation = activate_demo_strategy(
                    package=package,
                    run_id=run_id,
                    market_time=market_time,
                    signal=position_weight,
                    price=price,
                    previous_target_quantity=float(existing_demo.get("target_quantity") or 0.0),
                )
            except Exception as exc:  # noqa: BLE001 - 记录阻断并继续内部观察
                logger.warning("OKX Demo 再平衡被阻止 run=%s: %s", run_id, exc)
                demo_activation = {
                    "status": "blocked",
                    "error": trading_errors.redact(f"{type(exc).__name__}: {exc}"),
                    "live_trading_enabled": False,
                }
        try:
            demo_evidence = refresh_demo_evidence(
                strategy_id=package.payload.strategy_id,
                strategy_version=package.payload.version,
                symbol=package.payload.universe["symbols"][0],
            )
        except Exception as exc:  # noqa: BLE001 - 私有链路异常必须成为证据而非丢失观察
            logger.warning("OKX Demo 证据刷新失败 run=%s: %s", run_id, exc)
            demo_evidence = {
                "status": "unavailable",
                "error": trading_errors.redact(f"{type(exc).__name__}: {exc}"),
                "live_trading_enabled": False,
            }
    cost_amount = float(paper_order["fee"]) if paper_order is not None else 0.0
    cost = cost_amount / max(previous["equity"], 1e-12)
    net_return = gross_return - cost
    equity = previous["equity"] * (1 + net_return)
    peak = max([item["equity"] for item in prior] + [equity])
    drawdown = equity / peak - 1
    execution_record = {
        "signal_time": market_time,
        "tradable_time": market_time,
        "theoretical_price": price,
        "simulated_price": price,
        "slippage_bps": 0.0,
        "rejection_reason": None,
        "capacity_used": position_weight,
        "simulation_order_id": paper_order["simulation_order_id"] if paper_order else None,
        "simulation_execution_id": (
            paper_order["simulation_execution_id"] if paper_order else None
        ),
        "fee": cost_amount,
        "okx_demo_order_id": (
            (demo_activation.get("order") or {}).get("order_id") if demo_activation else None
        ),
    }
    _observation, inserted = store.append_factor_factory_observation(
        run_id,
        market_time=market_time,
        price=price,
        signal=signal,
        position_weight=position_weight,
        gross_return=gross_return,
        cost=cost,
        net_return=net_return,
        equity=equity,
        drawdown=drawdown,
        fill_rate=float(paper_order["fill_rate"]) if paper_order else 1.0,
        payload={
            "kind": "paper_mark",
            "new_market_bar": new_market_bar,
            "data_fingerprint": provenance["fingerprint"],
            "paper_position_quantity": position_quantity,
            "simulation_order": paper_order,
            "okx_demo": demo_activation,
            "okx_demo_evidence": demo_evidence,
            "execution": execution_record,
        },
    )
    observations = store.list_factor_factory_observations(run_id)
    latest = observations[-1]
    result = dict(run["result"])
    previous_paper = dict(result.get("paper", {}))
    execution_records = list(previous_paper.get("execution_records", []))
    simulation_order_ids = list(previous_paper.get("simulation_order_ids", []))
    if inserted:
        execution_records.append(execution_record)
        if paper_order is not None:
            simulation_order_ids.append(paper_order["simulation_order_id"])
    updated_demo = dict(previous_paper.get("okx_demo") or {})
    if updated_demo:
        activation_history = list(updated_demo.get("activation_history", []))
        prior_activation = dict(updated_demo.get("latest_activation") or {})
        if demo_activation is not None and (
            inserted
            or demo_activation.get("status") != prior_activation.get("status")
            or (demo_activation.get("order") or {}).get("order_id")
            != (prior_activation.get("order") or {}).get("order_id")
        ):
            activation_history.append(demo_activation)
        if demo_activation is not None:
            updated_demo["latest_activation"] = demo_activation
            if "target_quantity" in demo_activation:
                updated_demo["target_quantity"] = demo_activation["target_quantity"]
        updated_demo["activation_history"] = activation_history
        if demo_evidence is not None:
            updated_demo["latest_evidence"] = demo_evidence
    result["paper"] = {
        **previous_paper,
        "latest_market_time": latest["market_time"],
        "latest_equity": latest["equity"],
        "after_cost_return": latest["equity"] / req.initial_capital - 1,
        "maximum_drawdown": min(item["drawdown"] for item in observations),
        "observation_count": len(observations),
        "completed_rebalance_cycles": len(observations),
        "execution_records": execution_records,
        "simulation_order_ids": simulation_order_ids,
        "current_position_quantity": latest["payload"].get("paper_position_quantity"),
        "last_poll_inserted": inserted,
        "shared_ledger_mutated": False,
        "okx_demo": updated_demo or None,
        "live_trading_enabled": False,
    }
    run_for_validation = {**run, "result": result}
    monitoring = _monitor_drift(run, observations, req)
    degraded = _degrade_for_drift(run, req, monitoring) if monitoring else False
    if degraded:
        status = "degraded"
        validation = None
    else:
        status, validation = _finalize_paper_if_due(
            run_for_validation, observations, req, monitoring
        )
    result["monitoring"] = monitoring
    if validation is not None:
        result["simulation_validation"] = validation
    saved = store.update_factor_factory_run(run_id, status=status, result=result)
    return _detail(saved)


_monitor_stop = threading.Event()
_monitor_thread: threading.Thread | None = None
_auto_discovery_attempted_dates: dict[str, date] = {}


def _auto_discovery_enabled() -> bool:
    return (
        os.environ.get("QUANTHUB_FACTOR_AUTO_DISCOVERY", "0") == "1"
        and os.environ.get("QH_RUNNER_ENVIRONMENT", "shadow") == "demo"
    )


def _auto_discovery_request(interval: str) -> FactorFactoryStartRequest:
    return FactorFactoryStartRequest(
        source="okx_live",
        symbol="BTC-USDT-SWAP",
        interval=interval,
        n_bars=2_880 if interval == "1h" else 720,
        candidate_budget=30,
        candidate_mode="brain",
        use_ai=True,
        ai_candidate_count=6,
        paper_target="okx_demo",
        maximum_demo_exposure=0.1,
        maximum_demo_loss=25.0,
    )


def _run_auto_discovery_cycle(now: datetime | None = None) -> list[dict[str, Any]]:
    if not _auto_discovery_enabled():
        return []
    local_now = now or datetime.now().astimezone()
    try:
        configured_hour = int(os.environ.get("QUANTHUB_FACTOR_AUTO_HOUR", "10"))
    except ValueError:
        configured_hour = 10
    due_hour = max(0, min(23, configured_hour))
    if local_now.hour < due_hour:
        return []
    if store.list_factor_factory_runs(status="paper_observing", limit=1):
        return []

    today = local_now.date()
    existing_runs = store.list_factor_factory_runs(limit=200)
    outcomes: list[dict[str, Any]] = []
    for interval in ("1h", "4h"):
        if _auto_discovery_attempted_dates.get(interval) == today:
            continue
        matching = [
            run
            for run in existing_runs
            if run["config"].get("source") == "okx_live"
            and run["config"].get("symbol") == "BTC-USDT-SWAP"
            and run["config"].get("interval") == interval
            and run["config"].get("paper_target") == "okx_demo"
        ]
        ran_today = any(
            datetime.fromtimestamp(float(run["started_at"]), tz=local_now.tzinfo).date() == today
            for run in matching
        )
        boundary = market_data_module.current_bar_boundary(
            interval,
            now=local_now.astimezone(UTC),
        ).isoformat()
        latest_boundary = (
            matching[0]["config"].get("data_provenance", {}).get("requested_end")
            if matching
            else None
        )
        if ran_today or latest_boundary == boundary:
            _auto_discovery_attempted_dates[interval] = today
            outcomes.append(
                {
                    "interval": interval,
                    "status": "skipped",
                    "reason": "already_ran_today" if ran_today else "same_market_boundary",
                    "requested_end": boundary,
                }
            )
            continue

        _auto_discovery_attempted_dates[interval] = today
        try:
            result = start_factor_factory(_auto_discovery_request(interval))
        except Exception as exc:  # noqa: BLE001 - scheduler records and stops retry storms
            logger.exception("自动因子每日发现失败: %s", interval)
            outcomes.append(
                {
                    "interval": interval,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                    "requested_end": boundary,
                }
            )
            continue
        run = result["run"]
        outcomes.append(
            {
                "interval": interval,
                "status": run["status"],
                "run_id": run["id"],
                "idempotent_replay": bool(result.get("idempotent_replay")),
                "requested_end": run["config"].get("data_provenance", {}).get("requested_end"),
            }
        )
        existing_runs.insert(0, run)
        if run["status"] == "paper_observing":
            break
    return outcomes


def _monitor_loop() -> None:
    interval = max(30, int(os.environ.get("QUANTHUB_FACTOR_MONITOR_SECONDS", "300")))
    while not _monitor_stop.is_set():
        for run in store.list_factor_factory_runs(status="paper_observing", limit=100):
            try:
                observe_factor_factory(
                    run["id"], force_refresh=run["config"]["source"] == "okx_live"
                )
            except Exception:
                logger.exception("自动因子模拟观察失败: %s", run["id"])
        try:
            discovery_outcomes = _run_auto_discovery_cycle()
            if discovery_outcomes:
                logger.warning(
                    "factor_factory_auto_discovery_audit: %s",
                    json.dumps(discovery_outcomes, ensure_ascii=False, sort_keys=True),
                )
        except Exception:  # noqa: BLE001 - monitor must survive scheduler faults
            logger.exception("自动因子每日发现调度失败")
        if _monitor_stop.wait(interval):
            break


def start_monitor() -> None:
    global _monitor_thread
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _monitor_stop.clear()
    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        name="factor-factory-monitor",
        daemon=True,
    )
    _monitor_thread.start()


def stop_monitor() -> None:
    _monitor_stop.set()
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_thread.join(timeout=2)
