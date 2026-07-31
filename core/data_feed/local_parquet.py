"""本地 Parquet K 线数据源（离线优先）。

直接从 ``data/`` 目录读取已落地的 Parquet K 线，使所有策略
（A股 / 加密 / MT5）可在无网络、无 API 限频下回测与研究。

数据契约（已用 uv run --with pyarrow 实测验证）：
    列：time(int64) | open(float) | high(float) | low(float) | close(float) | tick_volume(int64)
    命名与 time 编码分三套约定（见 groups 配置）：
      - OKX / MT5 : ``{symbol}_{TF}.parquet``，TF∈{M1,M5,M15,M30,H1,H4,D1,W1,MN1}，time=unix 秒
      - A股个股   : ``{code}_{N}min.parquet``（5min/15min/60min），time=非 unix 顺序整数（见下方说明）
      - A股指数   : ``idx_{code}_{N}min.parquet``，time=非 unix 顺序整数，**且实测 OHLC 为负、volume=int64 最小值 → 疑似损坏/占位，默认 warn 并谨慎使用**

关于 A股 time 编码：
    实测个股 time 为 1719395、1719396 这类顺序整数（相邻 bar +1），并非 unix 秒。
    在未知其真实 epoch 前，**不猜测解码**——ordinal 模式下保留 ``bar_time`` 整数列用于保序，
    ``datetime`` 置 NaT 并打印 WARNING，待用户确认编码后改为 unix_seconds/minutes。
    （AlphaMaster 的因子引擎只用 K 线序列，时间顺序正确即可正常算特征/信号。）

用法（由 factory 按 configs/*.yaml 的 data_sources.local_parquet 自动构建）：
    src = get_data_source("crypto")        # 在线 OKX 优先，失败 fallback 到本地
    src = get_data_source("a_shares")     # 本地 parquet 优先，失败 fallback 到 akshare/东财
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from core.data_feed.base import DataSource, Interval
from core.data_feed.quality import normalize_ohlcv_rows

logger = logging.getLogger(__name__)

_KNOWN_TF = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1")


def _make_filename_regex(pattern: str) -> re.Pattern:
    """把 ``{code}/{symbol}/{tf}/{TF}`` 占位符编译为正则。

    例：``{code}_{tf}min.parquet`` → ``^(?P<code>[^_]+)_(?P<tf>[^_]+)min\\.parquet$``
    """
    rx = re.escape(pattern)
    for ph, grp in (
        ("{code}", "code"),
        ("{symbol}", "symbol"),
        ("{tf}", "tf"),
        ("{TF}", "TF"),
    ):
        rx = rx.replace(re.escape(ph), f"(?P<{grp}>[^_]+)")
    return re.compile("^" + rx + "$")


def _normalize_symbol(symbol: str, mode: str) -> str:
    """把请求 symbol 归一化为文件名中的 key。

    mode="code"  : A股代码，去交易所后缀（000001.SZ → 000001）
    mode="symbol": 加密/MT5，去斜杠与连字符并大写（ADA/USDT → ADAUSDT）
    """
    if mode == "code":
        return symbol.split(".")[0].strip()
    return symbol.upper().replace("/", "").replace("-", "").strip()


class LocalParquetSource(DataSource):
    """本地 Parquet K 线数据源。

    Args:
        root:   数据根目录（绝对，或相对仓库根）
        groups: 分组配置 {组名: {subdir, pattern, tf_map, symbol_norm, time_mode, warn}}
        time_mode: 全局默认 time 解码（"auto"|"unix_seconds"|"ordinal"），可被组级覆盖
        market: 该实例所属市场（写入返回的 DataFrame）
    """

    name = "local_parquet"
    market = "abstract"

    def __init__(
        self,
        root: str | Path,
        groups: dict[str, dict[str, Any]] | None = None,
        time_mode: str = "auto",
        market: str = "abstract",
    ) -> None:
        self.root = Path(root)
        self.groups = groups or {}
        self._default_time_mode = time_mode
        self.market = market
        self._regex = {
            g: _make_filename_regex(cfg["pattern"])
            for g, cfg in self.groups.items()
            if "pattern" in cfg
        }
        self._index = self._scan()
        logger.info(
            "[LocalParquet] 已索引 %d 个本地 K 线文件（root=%s，组=%s）",
            len(self._index),
            self.root,
            list(self.groups.keys()),
        )

    # ── 文件索引 ───────────────────────────────────────────────
    def _scan(self) -> dict[tuple[str, str, str], Path]:
        idx: dict[tuple[str, str, str], Path] = {}
        for gname, cfg in self.groups.items():
            rx = self._regex.get(gname)
            if rx is None:
                continue
            sub = self.root / cfg.get("subdir", "")
            if not sub.exists():
                logger.warning("[LocalParquet] 分组 %s 目录不存在: %s", gname, sub)
                continue
            norm = cfg.get("symbol_norm", "symbol")
            for p in sub.glob("*.parquet"):
                m = rx.match(p.name)
                if not m:
                    continue
                raw_key = m.group("symbol") if "symbol" in m.groupdict() else m.group("code")
                # 关键：索引键与 lookup 端（get_kline 内的 _normalize_symbol）
                # 必须走同一套归一化，否则大小写不一致会 miss。
                # 例：MT5 的 US30.cash 文件在 regex 捕获时为 "US30.cash"，
                # 若此处不归一化、而 lookup 端 .upper() 变成 "US30.CASH" → 查不到。
                sym_key = _normalize_symbol(raw_key, norm)
                tf_key = m.group("TF") if "TF" in m.groupdict() else m.group("tf")
                idx[(gname, sym_key, tf_key)] = p
        return idx

    # ── 公开接口 ───────────────────────────────────────────────
    def get_kline(
        self,
        symbol: str,
        interval: Interval | str,
        start: Any = None,
        end: Any = None,
        limit: int = 500,
    ) -> pd.DataFrame:
        interval = Interval(interval).value if not isinstance(interval, str) else interval
        cols = [
            "symbol",
            "market",
            "interval",
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover",
            "bar_time",
        ]

        for gname, cfg in self.groups.items():
            norm = cfg.get("symbol_norm", "symbol")
            key = _normalize_symbol(symbol, norm)
            tf_map: dict[str, str] = cfg.get("tf_map", {})
            file_tf = tf_map.get(interval)
            if file_tf is None:
                continue  # 该组无此周期文件，跳过
            path = self._index.get((gname, key, file_tf))
            if path is None or not path.exists():
                continue
            df = self._read(path, symbol, interval, cfg, gname)
            if df is None or df.empty:
                continue
            # 区间裁剪（优先用真实 datetime；ordinal 模式按 bar_time 裁剪）
            df = self._clip(df, start, end, limit)
            return df[cols]

        logger.debug("[LocalParquet] 未找到本地文件: %s %s", symbol, interval)
        return pd.DataFrame(columns=cols)

    # ── 内部 ───────────────────────────────────────────────────
    def _read(
        self, path: Path, symbol: str, interval: str, cfg: dict, gname: str
    ) -> pd.DataFrame | None:
        try:
            df = pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001 - parquet engines expose backend-specific errors
            logger.warning("[LocalParquet] 读取失败 %s: %s", path.name, exc)
            return None

        vol_col = "tick_volume" if "tick_volume" in df.columns else "volume"
        needed = ["time", "open", "high", "low", "close", vol_col]
        if any(c not in df.columns for c in needed):
            logger.warning("[LocalParquet] %s 缺列: %s", path.name, needed)
            return None

        df = df[needed].rename(columns={vol_col: "volume"}).copy()
        df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)

        # time 解码
        mode = cfg.get("time_mode", self._default_time_mode)
        if mode == "auto":
            mode = "unix_seconds" if df["time"].max() >= 1e9 else "ordinal"
        if mode == "unix_seconds":
            df["datetime"] = pd.to_datetime(df["time"], unit="s")
            df["bar_time"] = df["time"].astype("int64")
        else:  # ordinal：保留整数保序，datetime 置 NaT 并告警
            df["bar_time"] = df["time"].astype("int64")
            df["datetime"] = pd.NaT
            if cfg.get("warn", False) or gname.startswith("a_"):
                logger.warning(
                    "[LocalParquet] 分组 %s 的 time 为非 unix 编码（顺序整数），"
                    "datetime 为占位 NaT，仅 bar_time 保序；请确认编码后改 time_mode。",
                    gname,
                )

        df["symbol"] = symbol
        df["market"] = self.market
        df["interval"] = interval
        df["amount"] = pd.NA
        df["turnover"] = pd.NA
        if df["datetime"].notna().any():
            df = normalize_ohlcv_rows(df)
        else:
            df = normalize_ohlcv_rows(df, time_column="bar_time")
        return df

    def _clip(self, df: pd.DataFrame, start, end, limit: int) -> pd.DataFrame:
        # ordinal 模式 datetime 为 NaT，按 bar_time 裁剪；否则按 datetime
        if df["datetime"].notna().any():
            if start is not None:
                df = df[df["datetime"] >= pd.to_datetime(start)]
            if end is not None:
                df = df[df["datetime"] <= pd.to_datetime(end)]
        elif "bar_time" in df.columns:
            if isinstance(start, (int, float)):
                df = df[df["bar_time"] >= int(start)]
            if isinstance(end, (int, float)):
                df = df[df["bar_time"] <= int(end)]
        if limit and limit > 0 and len(df) > limit:
            df = df.tail(limit).reset_index(drop=True)
        return df.reset_index(drop=True)
