"""A股多因子选股神器 — QuantHub 迁移版。

从 trading-master/04-stock-selector 下沉为 strategies/a_shares/selector:
    - produce(): 用 core.data_feed 拉取 K 线 → 多因子评分 → 产出 top_n 个 Signal
    - 选股算法（短线 / 长线）保持原样，仅适配 QuantHub 数据层与 Signal 总线

短线评分体系（满分 100，源自 ShortTermSelector.analyze_single_stock）:
    RSI(20) + KDJ(20) + MACD(15) + 布林带(15) + 量价异动(15) + 资金流向(15)
长线评分体系（满分 100，源自 LongTermSelector.analyze_single_stock）:
    趋势(30) + 动量(15) + 量能(15) + 趋势强度(10) + 波动率(10) + 乖离率(10) + 资金流(10)

数据约束:
    - 行情数据优先用 core.data_feed.get_data_source("a_shares")
    - 指数成分股（universe）core.data_feed 暂不提供，经 akshare 获取
    - 资金流向 / 股票名称 core.data_feed 暂不提供，已标注 TODO
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
import pandas as pd

from core.data_feed import Interval, get_data_source
from core.signals import Signal
from strategies.a_shares.selector import indicators as ind
from strategies.base import StrategyBase, StrategyInfo, register_strategy

logger = logging.getLogger(__name__)

# 选股域别名 → 指数代码（akshare index_stock_cons 的 symbol）
_UNIVERSE_ALIAS: dict[str, str] = {
    "hs300": "000300",
    "沪深300": "000300",
    "sz50": "000016",
    "上证50": "000016",
    "zz500": "000905",
    "中证500": "000905",
    "zz1000": "000852",
    "中证1000": "000852",
}


def _to_json_safe(obj: Any) -> Any:
    """转换为 JSON 安全的数据类型（处理 numpy/pandas 类型与 NaN）。"""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(item) for item in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        val = float(obj)
        return None if (math.isnan(val) or math.isinf(val)) else val
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _get_gem_star_stocks(ak) -> list[str]:
    """获取创业板（399006）+ 科创50（000688）成分股。"""
    codes: set = set()
    for symbol, prefix, label in [("399006", "3", "创业板"), ("000688", "688", "科创50")]:
        try:
            df = ak.index_stock_cons(symbol=symbol)
            for c in df["品种代码"].astype(str).str.zfill(6).tolist():
                if c.startswith(prefix):
                    codes.add(c)
        except Exception:
            logger.warning("%s成分股获取失败", label, exc_info=True)
    return sorted(codes)


def _get_index_constituents(universe: str) -> list[str]:
    """解析选股域并返回成分股代码列表。

    core.data_feed 暂不提供指数成分股接口，这里经 akshare 获取
    （akshare 已声明为本模块依赖）。排除创业板(3开头)与科创板(688开头)，
    与原 selectors 行为一致；gem_star 域反其道仅保留这两类。
    """
    try:
        import akshare as ak
    except ImportError as e:
        raise ImportError("akshare 未安装，请运行: pip install akshare") from e

    index_code = _UNIVERSE_ALIAS.get(universe, universe)  # 未命中别名则视为直接指数代码

    if index_code == "gem_star":
        return _get_gem_star_stocks(ak)

    def _filter(codes: list[str]) -> list[str]:
        return [c for c in codes if not c.startswith("3") and not c.startswith("688")]

    # 方案1: 东方财富成分股接口（稳定）
    try:
        df = ak.index_stock_cons(symbol=index_code)
        codes = df["品种代码"].astype(str).str.zfill(6).tolist()
        result = _filter(codes)
        logger.debug("选股域 %s 成分股 %d 只", index_code, len(result))
        return result
    except Exception:
        logger.warning("东方财富成分股获取失败: %s", index_code, exc_info=True)

    # 方案2: 中证指数官网（fallback）
    try:
        df = ak.index_stock_cons_weight_csindex(symbol=index_code)
        codes = df["成分券代码"].astype(str).str.zfill(6).tolist()
        result = _filter(codes)
        logger.debug("选股域 %s 成分股(csindex) %d 只", index_code, len(result))
        return result
    except Exception:
        logger.warning("中证官网成分股获取失败: %s", index_code, exc_info=True)

    logger.error("所有成分股数据源均失败: %s", index_code)
    return []


def _rating_short(score: float) -> str:
    """短线评级。"""
    if score >= 85:
        return "A+"
    if score >= 70:
        return "A"
    if score >= 60:
        return "B+"
    if score >= 50:
        return "B"
    return "C"


def _rating_long(score: float) -> str:
    """长线评级。"""
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    if score >= 65:
        return "B+"
    if score >= 55:
        return "B"
    if score >= 45:
        return "C"
    return "D"


def _score_short(df: pd.DataFrame, fund_flow: dict | None = None) -> dict | None:
    """短线多因子评分（源自 ShortTermSelector.analyze_single_stock，算法原样）。

    Args:
        df        : 日线 OHLCV DataFrame（需含 close/high/low/volume，长度 >= 20）
        fund_flow : 资金流数据 {'main_in': float}；core.data_feed 暂不提供，默认 None
    """
    if df is None or df.empty or len(df) < 10:
        return None

    current_price = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    change_pct = (current_price - prev_close) / prev_close * 100 if prev_close else 0.0

    score = 0
    details: dict = {}
    buy_signals: list[str] = []
    sell_signals: list[str] = []

    # ====== 1. RSI 超卖反弹 (20分) ======
    rsi = ind.calc_rsi(df)
    rsi_now = rsi.iloc[-1]

    rsi_score = 0
    rsi_signal = None
    if rsi_now < 30:
        rsi_score = 20
        rsi_signal = f"RSI超卖 ({rsi_now:.0f})"
        buy_signals.append(rsi_signal)
    elif rsi_now < 40:
        rsi_score = 12
        rsi_signal = f"RSI偏低 ({rsi_now:.0f})"
    elif 40 <= rsi_now <= 60:
        rsi_score = 5
    elif rsi_now > 70:
        rsi_score = 0
        rsi_signal = f"RSI超买 ({rsi_now:.0f})"
        sell_signals.append(rsi_signal)

    score += rsi_score
    details["rsi"] = {"score": rsi_score, "value": rsi_now, "signal": rsi_signal}

    # ====== 2. KDJ 金叉 (20分) ======
    k, d, j = ind.calc_kdj(df)
    kdj_result = ind.detect_kdj_cross(k, d, j)

    kdj_score = 0
    if kdj_result["golden_cross"] and kdj_result["j"] < 50:
        kdj_score = 20
        buy_signals.append(f"KDJ金叉 (K={kdj_result['k']:.0f}, J={kdj_result['j']:.0f})")
    elif kdj_result["oversold"]:
        kdj_score = 15
        buy_signals.append(f"KDJ超卖 (J={kdj_result['j']:.0f})")
    elif kdj_result["dead_cross"] and kdj_result["j"] > 70:
        kdj_score = -10
        sell_signals.append(f"KDJ死叉 (K={kdj_result['k']:.0f}, J={kdj_result['j']:.0f})")
    elif kdj_result["overbought"]:
        kdj_score = -5
        sell_signals.append(f"KDJ超买 (J={kdj_result['j']:.0f})")
    elif kdj_result["score"] > 0:
        kdj_score = kdj_result["score"]

    score += max(0, kdj_score)  # 负分不计入总分
    kdj_signal = kdj_result["signals"][0] if kdj_result["signals"] else ""
    details["kdj"] = {
        "score": max(0, kdj_score),
        "k": kdj_result["k"],
        "d": kdj_result["d"],
        "j": kdj_result["j"],
        "signal": kdj_signal,
        "golden_cross": kdj_result["golden_cross"],
        "death_cross": kdj_result["dead_cross"],
    }

    # ====== 3. MACD 信号 (15分) ======
    dif, dea, macd_hist = ind.calc_macd_short(df)
    macd_result = ind.detect_macd_cross(dif, dea, macd_hist)

    macd_score = 0
    macd_signals = macd_result["signals"]
    macd_signal = macd_signals[0] if macd_signals else ""
    if macd_result["golden_cross"]:
        macd_score = 15
        buy_signals.append(f"MACD金叉 (DIF={macd_result['dif']:.3f})")
    elif any("红柱扩张" in s for s in macd_signals):
        macd_score = 10
        buy_signals.append("MACD红柱扩张")
    elif macd_result["histogram"] < 0 and macd_result["dif"] < macd_result["dea"]:
        macd_score = -10
        sell_signals.append(f"MACD死叉 (DIF={macd_result['dif']:.3f})")
    elif any("红柱" in s for s in macd_signals):
        macd_score = 5
    elif macd_result["histogram"] > 0 and macd_result["dif"] > macd_result["dea"]:
        macd_score = 8  # MACD 多头

    score += max(0, macd_score)
    details["macd"] = {
        "score": max(0, macd_score),
        "dif": macd_result["dif"],
        "dea": macd_result["dea"],
        "macd_hist": macd_result["histogram"],
        "signal": macd_signal,
        "golden_cross": macd_result["golden_cross"],
        "death_cross": macd_result["histogram"] < 0 and macd_result["dif"] < macd_result["dea"],
    }

    # ====== 4. 布林带信号 (15分) ======
    upper, middle, lower = ind.calc_bollinger(df)
    boll_result = ind.detect_bollinger_signal(df, upper, middle, lower)

    boll_score = 0
    boll_signals = boll_result["signals"]
    boll_signal = boll_signals[0] if boll_signals else ""
    boll_position_pct = boll_result["price_position"] * 100
    if any("下轨" in s for s in boll_signals):
        boll_score = 15
        buy_signals.append(f"布林下轨支撑 (位置{boll_position_pct:.0f}%)")
    elif any("中轨" in s for s in boll_signals):
        boll_score = 10
        buy_signals.append("布林中轨支撑")
    elif any("上轨" in s for s in boll_signals):
        boll_score = -5
        sell_signals.append("布林触及上轨")
    elif boll_position_pct < 30:
        boll_score = 8  # 偏下轨

    score += max(0, boll_score)
    details["bollinger"] = {
        "score": max(0, boll_score),
        "upper": boll_result["upper"],
        "middle": boll_result["middle"],
        "lower": boll_result["lower"],
        "bandwidth": boll_result["bandwidth"],
        "position_pct": boll_position_pct,
        "signal": boll_signal,
    }

    # ====== 5. 量价异动 (15分) ======
    volume_surge = ind.detect_volume_surge(df, ratio=1.5)

    volume_score = 0
    vol_signals = volume_surge["signals"]
    vol_signal = vol_signals[0] if vol_signals else ""
    vol_ratio = volume_surge["volume_ratio"]
    price_up = volume_surge["price_up"]
    if any("放量上涨" in s for s in vol_signals):
        volume_score = 15
        buy_signals.append(f"放量突破 (量比{vol_ratio:.1f})")
    elif vol_ratio > 1.5 and price_up:
        volume_score = 12
        buy_signals.append(f"温和放量 (量比{vol_ratio:.1f})")
    elif vol_ratio > 1.5 and not price_up:
        volume_score = -10
        sell_signals.append(f"放量下跌 (量比{vol_ratio:.1f})")
    elif any("缩量" in s for s in vol_signals) and price_up:
        volume_score = 5

    score += max(0, volume_score)
    details["volume"] = {
        "score": max(0, volume_score),
        "volume_ratio": vol_ratio,
        "price_change": float(price_up),
        "surge_type": vol_signal,
    }

    # ====== 6. 资金流向 (15分) ======
    # TODO: core.data_feed 暂不提供资金流数据；fund_flow 默认 None，fund_score=0
    fund_score = 0
    fund_signal = None
    main_in_wan = 0.0
    if fund_flow:
        main_in = fund_flow.get("main_in", 0)
        main_in_wan = main_in / 10000  # 转换为万
        if main_in > 5000000:  # 主力流入 > 500 万
            fund_score = 15
            fund_signal = f"主力流入 (+{main_in_wan:.0f}万)"
            buy_signals.append(fund_signal)
        elif main_in > 0:
            fund_score = 8
            fund_signal = f"小幅流入 (+{main_in_wan:.0f}万)"
        elif main_in < -5000000:
            fund_score = 0
            fund_signal = f"主力流出 ({main_in_wan:.0f}万)"
            sell_signals.append(fund_signal)

    score += fund_score
    details["fund_flow"] = {
        "score": fund_score,
        "main_in": main_in_wan,
        "signal": fund_signal,
    }

    # ====== 7. ATR 动态止损止盈 ======
    atr = ind.calc_atr_short(df)
    atr_now = atr.iloc[-1]
    trade_points = ind.calc_trade_points(
        current_price,
        atr_now,
        stop_multiplier=2.0,
        profit_multiplier=3.0,
    )
    trade_points["atr"] = round(float(atr_now), 4)
    trade_points["atr_pct"] = round(float(atr_now / current_price * 100) if current_price else 0, 2)

    buy_signal_count = len(buy_signals)
    sell_signal_count = len(sell_signals)

    return {
        "price": current_price,
        "change_pct": change_pct,
        "score": round(float(score), 2),
        "rating": _rating_short(score),
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "buy_signal_count": buy_signal_count,
        "sell_signal_count": sell_signal_count,
        "details": details,
        "buy_price": trade_points["buy_price"],
        "stop_loss": trade_points["stop_loss"],
        "take_profit": trade_points["take_profit"],
        "stop_loss_pct": trade_points["stop_loss_pct"],
        "take_profit_pct": trade_points["take_profit_pct"],
        "risk_reward_ratio": trade_points["risk_reward_ratio"],
        "atr": trade_points["atr"],
        "atr_pct": trade_points["atr_pct"],
        "recommend": bool(score >= 60 and buy_signal_count >= 2),
    }


def _score_long(df: pd.DataFrame, fund_flow: dict | None = None) -> dict | None:
    """长线多因子评分（源自 LongTermSelector.analyze_single_stock，算法原样）。

    Args:
        df        : 日线 OHLCV DataFrame（需含 close/high/low/volume，长度 >= 60）
        fund_flow : 资金流数据 {'main_in': float}；core.data_feed 暂不提供，默认 None
    """
    if df is None or df.empty or len(df) < 60:
        return None

    current_price = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    change_pct = (current_price - prev_close) / prev_close * 100 if prev_close else 0.0

    score = 0
    details: dict = {}

    # ====== 1. 趋势评分 (30分) ======
    trend = ind.score_trend(df)
    trend_score = trend["score"] * 0.30  # 转换为 30 分制
    score += trend_score
    details["trend"] = {
        "score": trend_score,
        "rating": trend["rating"],
        "reasons": trend["reasons"],
        "ma20": trend["ma20"],
        "ma60": trend["ma60"],
    }

    # ====== 2. 动量评分 (15分) ======
    returns_5d = (df["close"].iloc[-1] - df["close"].iloc[-6]) / df["close"].iloc[-6] * 100
    returns_20d = (df["close"].iloc[-1] - df["close"].iloc[-21]) / df["close"].iloc[-21] * 100

    momentum_score = 0
    if returns_5d > 0:
        momentum_score += 5
    if returns_20d > 0:
        momentum_score += 10

    score += momentum_score
    details["momentum"] = {
        "score": momentum_score,
        "returns_5d": returns_5d,
        "returns_20d": returns_20d,
    }

    # ====== 3. 量能评分 (15分) ======
    obv = ind.calc_obv(df)
    vol_ratio = ind.calc_volume_ratio(df)

    volume_score = 0
    # OBV 上升
    if obv.iloc[-1] > obv.iloc[-20]:
        volume_score += 8
    # 量比合理（0.8-2.0）
    if 0.8 < vol_ratio.iloc[-1] < 2.0:
        volume_score += 7

    score += volume_score
    details["volume"] = {
        "score": volume_score,
        "obv_trend": "up" if obv.iloc[-1] > obv.iloc[-20] else "down",
        "volume_ratio": vol_ratio.iloc[-1],
    }

    # ====== 4. 趋势强度 (10分) ======
    adx, plus_di, minus_di = ind.calc_adx(df)

    strength_score = 0
    if adx.iloc[-1] > 25:  # ADX > 25 表示趋势明显
        strength_score += 5
    if plus_di.iloc[-1] > minus_di.iloc[-1]:  # 多头强势
        strength_score += 5

    score += strength_score
    details["strength"] = {
        "score": strength_score,
        "adx": adx.iloc[-1],
        "plus_di": plus_di.iloc[-1],
        "minus_di": minus_di.iloc[-1],
    }

    # ====== 5. 波动率评分 (10分) ======
    atr = ind.calc_atr(df)
    volatility = df["close"].pct_change().std() * np.sqrt(252) * 100

    volatility_score = 0
    # 波动率适中（15-35% 年化）
    if 15 < volatility < 35:
        volatility_score = 10
    elif 10 < volatility <= 15 or 35 <= volatility < 50:
        volatility_score = 5

    score += volatility_score
    details["volatility"] = {
        "score": volatility_score,
        "annual_volatility": volatility,
        "atr": atr.iloc[-1],
    }

    # ====== 6. 乖离率评分 (10分) ======
    bias = ind.calc_bias(df, period=20)

    bias_score = 0
    # 乖离率在合理范围(-10% ~ +15%)
    if -10 < bias.iloc[-1] < 15:
        bias_score = 10
    elif -15 < bias.iloc[-1] <= -10 or 15 <= bias.iloc[-1] < 20:
        bias_score = 5

    score += bias_score
    details["bias"] = {
        "score": bias_score,
        "bias_value": bias.iloc[-1],
    }

    # ====== 7. 资金流评分 (10分) ======
    # TODO: core.data_feed 暂不提供资金流数据；无数据时 fund_score=5（与原逻辑一致）
    fund_score = 0
    main_in_wan = 0.0
    if fund_flow:
        main_in = fund_flow.get("main_in", 0)
        main_in_wan = main_in / 10000
        if main_in > 0:
            fund_score = 10
        elif main_in > -100000000:  # 流出不严重
            fund_score = 5
    else:
        fund_score = 5  # 无数据给中等分

    score += fund_score
    details["fund_flow"] = {
        "score": fund_score,
        "main_in": main_in_wan,
    }

    # ====== 8. 买卖点（中长线：固定 -8% 止损 / +20% 止盈） ======
    # 中长线持股周期长（20-180日），使用固定幅度而非 ATR 动态计算
    # 止损 -8%：接受正常波动，避免被中线震仓洗出
    # 止盈 +20%：对应一波主升浪目标，风险收益比 2.5:1
    stop_loss = current_price * 0.92
    take_profit = current_price * 1.20
    stop_loss_pct = -8.0
    take_profit_pct = 20.0
    risk_reward_ratio = 2.5

    # 生成买入信号列表
    buy_signals: list[str] = []
    if trend["rating"] in ["强势上涨", "稳健上涨"]:
        buy_signals.append(f"趋势良好 ({trend['rating']})")
    if returns_20d > 5:
        buy_signals.append(f"20日涨幅 (+{returns_20d:.1f}%)")
    if obv.iloc[-1] > obv.iloc[-20]:
        buy_signals.append("OBV持续上升")
    if adx.iloc[-1] > 25 and plus_di.iloc[-1] > minus_di.iloc[-1]:
        buy_signals.append(f"趋势强度高 (ADX={adx.iloc[-1]:.0f})")
    if fund_flow and fund_flow.get("main_in", 0) > 0:
        buy_signals.append(f"主力流入 (+{fund_flow.get('main_in', 0) / 10000:.0f}万)")

    return {
        "price": current_price,
        "change_pct": change_pct,
        "score": round(float(score), 2),
        "rating": _rating_long(score),
        "buy_signals": buy_signals,
        "sell_signals": [],
        "buy_signal_count": len(buy_signals),
        "sell_signal_count": 0,
        "details": details,
        "buy_price": round(current_price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "stop_loss_pct": round(stop_loss_pct, 2),
        "take_profit_pct": round(take_profit_pct, 2),
        "risk_reward_ratio": round(risk_reward_ratio, 2),
        "recommend": bool(score >= 70),  # 70 分以上推荐
    }


@register_strategy(
    StrategyInfo(
        name="selector",
        market="a_shares",
        live_capable=False,
        description="多因子选股神器",
    )
)
class SelectorStrategy(StrategyBase):
    """A股多因子选股策略（短线 / 长线）。"""

    def produce(
        self,
        universe: str = "hs300",
        term: str = "short",
        top_n: int = 20,
        **kwargs: Any,
    ) -> list[Signal]:
        """扫描选股域，按多因子评分产出 top_n 个买入信号。

        Args:
            universe : 选股域（hs300 / sz50 / zz500 / zz1000 / gem_star 或指数代码）
            term     : 选股周期 "short"（短线，30日）| "long"（长线，120日）
            top_n    : 返回评分最高的前 N 只
        """
        term = str(term).lower()
        if term not in ("short", "long"):
            raise ValueError(f"term 仅支持 short/long，得到 {term}")

        source = get_data_source("a_shares")
        codes = _get_index_constituents(universe)
        if not codes:
            logger.warning("选股域为空: %s", universe)
            return []

        # 短线 30 交易日 / 长线 120 交易日（limit 为日历日，留余量）
        limit = 90 if term == "short" else 400
        min_len = 20 if term == "short" else 60
        scorer = _score_short if term == "short" else _score_long

        logger.info(
            "选股扫描: universe=%s term=%s codes=%d top_n=%d", universe, term, len(codes), top_n
        )

        results: list[dict] = []
        for i, code in enumerate(codes, 1):
            try:
                df = source.get_kline(code, Interval.DAILY, limit=limit)
            except Exception:
                logger.exception("获取 K 线失败: %s", code)
                continue
            if df is None or df.empty or len(df) < min_len:
                continue

            # TODO: 资金流向数据 core.data_feed 暂不提供，传 None
            result = scorer(df, fund_flow=None)
            if result is None:
                continue
            result["code"] = code
            # TODO: 股票名称 core.data_feed 暂不提供，暂以代码占位
            result["name"] = code
            results.append(result)

        # 按评分排序，取 top_n
        results.sort(key=lambda x: x["score"], reverse=True)
        top = results[:top_n]

        signals: list[Signal] = []
        for r in top:
            sig = self._to_signal(r, term, universe)
            if sig is not None:
                signals.append(sig)
                self.publish(sig)
        return signals

    @staticmethod
    def _to_signal(r: dict, term: str, universe: str) -> Signal | None:
        """把单只股票评分结果转为 Signal。"""
        raw = float(r["score"])
        norm = max(0.0, min(1.0, raw / 100.0))
        buy_cnt = int(r.get("buy_signal_count", 0))
        # confidence：买入信号共振数越多置信度越高
        confidence = float(min(1.0, 0.4 + 0.15 * buy_cnt))
        return Signal(
            symbol=r["code"],
            market="a_shares",
            timeframe="daily",
            direction="buy",
            score=norm,
            confidence=confidence,
            source="selector",
            tags=[term, str(r.get("rating", "")), f"universe={universe}"],
            meta={
                "name": r.get("name", r["code"]),
                "price": r.get("price"),
                "change_pct": r.get("change_pct"),
                "raw_score": raw,
                "rating": r.get("rating"),
                "recommend": r.get("recommend"),
                "buy_signals": r.get("buy_signals", []),
                "sell_signals": r.get("sell_signals", []),
                "buy_signal_count": buy_cnt,
                "sell_signal_count": int(r.get("sell_signal_count", 0)),
                "buy_price": r.get("buy_price"),
                "stop_loss": r.get("stop_loss"),
                "take_profit": r.get("take_profit"),
                "stop_loss_pct": r.get("stop_loss_pct"),
                "take_profit_pct": r.get("take_profit_pct"),
                "risk_reward_ratio": r.get("risk_reward_ratio"),
                "details": _to_json_safe(r.get("details", {})),
                "term": term,
            },
        )

    def run_daily_select(
        self,
        universe: str = "hs300",
        term: str = "short",
        top_n: int = 20,
        **kwargs: Any,
    ) -> list[Signal]:
        """供 scheduler 调用的每日选股入口（默认短线 TOP 20）。"""
        return self.produce(universe=universe, term=term, top_n=top_n, **kwargs)


def run_daily_select(
    universe: str = "hs300",
    term: str = "short",
    top_n: int = 20,
    **kwargs: Any,
) -> list[Signal]:
    """便捷选股入口：实例化 SelectorStrategy 并产出信号。"""
    strategy = SelectorStrategy(config={"enabled": True})
    return strategy.run_daily_select(universe=universe, term=term, top_n=top_n, **kwargs)
