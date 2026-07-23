"""选股指标计算库 — 从 trading-master/04-stock-selector 下沉。

包含两套指标（算法保持原样，严禁改动公式）:
    - 短线指标（源自 selectors/short_term_indicators.py）:
        RSI / KDJ / MACD / 布林带 / 量价异动 / 短线 ATR / 买卖点
    - 长线指标（源自 selectors/advanced_indicators.py）:
        趋势评分 / OBV / 量比 / ADX / ATR / 乖离率

列名约定：输入 DataFrame 需含 close / high / low / volume 列
（core.data_feed 返回的小写列名直接可用）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════════════════════
# 短线指标（源自 short_term_indicators.py，公式逐字保留）
# ═══════════════════════════════════════════════════════════════════════════


def calc_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """RSI 相对强弱指标。"""
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_kdj(df: pd.DataFrame, n: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """KDJ 随机指标。"""
    low_min = df["low"].rolling(n).min()
    high_max = df["high"].rolling(n).max()
    rsv = (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan) * 100
    rsv = rsv.fillna(50)
    k = rsv.ewm(com=2, min_periods=1).mean()
    d = k.ewm(com=2, min_periods=1).mean()
    j = 3 * k - 2 * d
    return k, d, j


def detect_kdj_cross(k: pd.Series, d: pd.Series, j: pd.Series) -> dict:
    """KDJ 金叉/死叉检测。"""
    k_prev, k_cur = k.iloc[-2], k.iloc[-1]
    d_prev, d_cur = d.iloc[-2], d.iloc[-1]
    j_cur = j.iloc[-1]
    golden = k_prev < d_prev and k_cur > d_cur
    dead = k_prev > d_prev and k_cur < d_cur
    oversold = k_cur < 30 and d_cur < 30
    overbought = k_cur > 80 and d_cur > 80
    score, signals = 0, []
    if golden and oversold:
        score = 20
        signals.append("KDJ超卖金叉")
    elif golden:
        score = 15
        signals.append("KDJ金叉")
    elif oversold:
        score = 10
        signals.append("KDJ超卖")
    elif overbought:
        score = 0
        signals.append("KDJ超买")
    elif not dead:
        score = 8
    return {
        "score": score,
        "signals": signals,
        "k": k_cur,
        "d": d_cur,
        "j": j_cur,
        "golden_cross": golden,
        "dead_cross": dead,
        "oversold": oversold,
        "overbought": overbought,
    }


def calc_macd_short(
    df: pd.DataFrame, fast=12, slow=26, signal=9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD 指标（短线版，hist * 2）。"""
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def detect_macd_cross(dif: pd.Series, dea: pd.Series, hist: pd.Series) -> dict:
    """MACD 金叉/红柱检测。"""
    dif_cur, dif_prev = dif.iloc[-1], dif.iloc[-2]
    dea_cur, dea_prev = dea.iloc[-1], dea.iloc[-2]
    hist_cur, hist_prev = hist.iloc[-1], hist.iloc[-2]
    golden = dif_prev < dea_prev and dif_cur > dea_cur
    red_col = hist_cur > 0
    shrink = hist_cur > 0 and hist_cur < hist_prev  # 红柱缩短
    score, signals = 0, []
    if golden and dif_cur < 0:
        score = 15
        signals.append("MACD零轴下方金叉")
    elif golden:
        score = 12
        signals.append("MACD金叉")
    elif red_col and not shrink:
        score = 10
        signals.append("MACD红柱扩张")
    elif red_col:
        score = 5
        signals.append("MACD红柱")
    return {
        "score": score,
        "signals": signals,
        "golden_cross": golden,
        "histogram": hist_cur,
        "dif": dif_cur,
        "dea": dea_cur,
    }


def calc_bollinger(
    df: pd.DataFrame, period=20, std_dev=2
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """布林带。"""
    mid = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def detect_bollinger_signal(
    df: pd.DataFrame, upper: pd.Series, middle: pd.Series, lower: pd.Series
) -> dict:
    """布林带信号检测。"""
    price = df["close"].iloc[-1]
    score, signals = 0, []
    bw = (upper.iloc[-1] - lower.iloc[-1]) / middle.iloc[-1]  # bandwidth
    if price <= lower.iloc[-1]:
        score = 15
        signals.append("布林下轨支撑")
    elif price <= middle.iloc[-1]:
        score = 10
        signals.append("布林中轨以下，有上升空间")
    elif price >= upper.iloc[-1]:
        score = 0
        signals.append("布林上轨，注意压力")
    else:
        score = 8
    return {
        "score": score,
        "signals": signals,
        "upper": upper.iloc[-1],
        "middle": middle.iloc[-1],
        "lower": lower.iloc[-1],
        "bandwidth": bw,
        "price_position": (price - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]),
    }


def detect_volume_surge(df: pd.DataFrame, ratio: float = 1.5) -> dict:
    """量价异动检测。"""
    avg_vol = df["volume"].rolling(20).mean().iloc[-1]
    cur_vol = df["volume"].iloc[-1]
    vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 1.0
    price_up = df["close"].iloc[-1] > df["close"].iloc[-2]
    score, signals = 0, []
    if vol_ratio >= ratio and price_up:
        score = 15
        signals.append(f"放量上涨({vol_ratio:.1f}倍)")
    elif vol_ratio >= ratio:
        score = 5
        signals.append(f"放量({vol_ratio:.1f}倍)")
    elif vol_ratio < 0.5:
        score = 3
        signals.append("缩量")
    else:
        score = 8
    return {"score": score, "signals": signals, "volume_ratio": vol_ratio, "price_up": price_up}


def calc_atr_short(df: pd.DataFrame, period: int = 10) -> pd.Series:
    """短线 ATR（SMA, period=10）。"""
    high, low, close_prev = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([high - low, (high - close_prev).abs(), (low - close_prev).abs()], axis=1).max(
        axis=1
    )
    return tr.rolling(period).mean()


def calc_trade_points(
    current_price: float,
    atr_value: float,
    stop_multiplier: float = 2.0,
    profit_multiplier: float = 3.0,
) -> dict:
    """基于 ATR 的动态止损止盈买卖点。"""
    if atr_value > 0 and current_price > 0:
        stop_loss = current_price - atr_value * stop_multiplier
        take_profit = current_price + atr_value * profit_multiplier
    else:
        stop_loss = current_price * 0.93
        take_profit = current_price * 1.15
    stop_loss_pct = (stop_loss - current_price) / current_price * 100
    take_profit_pct = (take_profit - current_price) / current_price * 100
    risk = current_price - stop_loss
    reward = take_profit - current_price
    rr = reward / risk if risk > 0 else 1.5
    return {
        "buy_price": round(current_price, 2),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "stop_loss_pct": round(stop_loss_pct, 2),
        "take_profit_pct": round(take_profit_pct, 2),
        "risk_reward_ratio": round(rr, 2),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 长线指标（源自 advanced_indicators.py，公式逐字保留）
# ═══════════════════════════════════════════════════════════════════════════


def score_trend(df: pd.DataFrame) -> dict:
    """MA 多头排列趋势评分，满分 100 分。"""
    close = df["close"]
    ma5 = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    price = close.iloc[-1]
    score, reasons = 0, []

    # 多头排列
    if ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
        score += 40
        reasons.append("均线完美多头排列")
    elif ma5.iloc[-1] > ma20.iloc[-1] > ma60.iloc[-1]:
        score += 30
        reasons.append("均线多头排列")
    elif ma5.iloc[-1] > ma20.iloc[-1]:
        score += 20
        reasons.append("短期均线在中期上方")

    # 价格位置
    if price > ma5.iloc[-1]:
        score += 20
        reasons.append("价格站上MA5")
    if price > ma20.iloc[-1]:
        score += 20
        reasons.append("价格站上MA20")
    if price > ma60.iloc[-1]:
        score += 20
        reasons.append("价格站上MA60")

    # 斜率（MA20 5日内是否上行）
    if ma20.iloc[-1] > ma20.iloc[-5]:
        score = min(100, score + 10)
        reasons.append("MA20向上")

    if score >= 80:
        rating = "强势上涨"
    elif score >= 60:
        rating = "稳健上涨"
    elif score >= 40:
        rating = "震荡偏强"
    elif score >= 20:
        rating = "震荡偏弱"
    else:
        rating = "下行趋势"

    return {
        "score": score,
        "rating": rating,
        "reasons": reasons,
        "ma5": ma5.iloc[-1],
        "ma10": ma10.iloc[-1],
        "ma20": ma20.iloc[-1],
        "ma60": ma60.iloc[-1],
    }


def calc_obv(df: pd.DataFrame) -> pd.Series:
    """OBV 能量潮。"""
    direction = np.sign(df["close"].diff().fillna(0))
    return (direction * df["volume"]).cumsum()


def calc_volume_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """量比。"""
    avg = df["volume"].rolling(period).mean()
    return df["volume"] / avg.replace(0, np.nan)


def calc_adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX / +DI / -DI 趋势强度指标。"""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx, plus_di, minus_di


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR（Wilder EMA, period=14）。"""
    high, low, prev_close = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )
    return tr.ewm(span=period, adjust=False).mean()


def calc_bias(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """乖离率 Bias。"""
    ma = df["close"].rolling(period).mean()
    return (df["close"] - ma) / ma.replace(0, np.nan) * 100
