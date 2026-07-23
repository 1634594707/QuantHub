# -*- coding: utf-8 -*-
"""指数 parquet 损坏修复（P-C，可选执行）。

只读调研结论见 docs/DATA_QUALITY.md。本脚本**默认 dry-run**（只统计、不写文件）；
需显式 ``--apply`` 才落盘，且落盘前自动备份原文件到
``data/parquet/indices/_backup_<时间戳>/``。

修复逻辑：
    - 模式 drop（默认）：删除 OHLC 任一 <=0 或 high<low 的整行（价格非法）。
    - 模式 flip：将负 OHLC 翻转为正（仅当你确认损坏是「符号写反」时用）。
    - tick_volume == int64.min 哨兵 → 置为 pd.NA（保留行，仅清空缺失量）。

用法：
    uv run python tools/repair_indices_parquet.py            # 仅统计
    uv run python tools/repair_indices_parquet.py --apply   # 真正修复（先备份）
    uv run python tools/repair_indices_parquet.py --apply --mode flip
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

SENTINEL = -9223372036854775808  # int64.min，缺失成交量哨兵
ROOT = Path(__file__).resolve().parent.parent
IDX_DIR = ROOT / "data" / "parquet" / "indices"
BACKUP_ROOT = IDX_DIR / "_backup"


def _repair(df: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, int, int]:
    """返回 (修复后df, 删除行数, 体积哨兵修正数)。"""
    ohlc_cols = ["open", "high", "low", "close"]
    has_ohlc = set(ohlc_cols).issubset(df.columns)
    has_vol = "tick_volume" in df.columns

    dropped = 0
    vol_fixed = 0

    if has_ohlc:
        invalid = (
            (df["open"] <= 0) | (df["high"] <= 0)
            | (df["low"] <= 0) | (df["close"] <= 0)
            | (df["high"] < df["low"])
        )
        if mode == "flip":
            # 符号翻转：把非法 OHLC 行整体取反（假设源导出符号写反）
            flip_mask = invalid
            for c in ohlc_cols:
                df.loc[flip_mask, c] = -df.loc[flip_mask, c]
            invalid = (
                (df["open"] <= 0) | (df["high"] <= 0)
                | (df["low"] <= 0) | (df["close"] <= 0)
                | (df["high"] < df["low"])
            )
        dropped = int(invalid.sum())
        df = df[~invalid].copy()
    else:
        df = df.copy()

    if has_vol:
        vol_mask = df["tick_volume"] == SENTINEL
        vol_fixed = int(vol_mask.sum())
        df.loc[vol_mask, "tick_volume"] = pd.NA

    return df, dropped, vol_fixed


def main() -> None:
    ap = argparse.ArgumentParser(description="指数 parquet 损坏修复（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="真正落盘（默认仅统计）")
    ap.add_argument("--mode", choices=["drop", "flip"], default="drop",
                    help="drop=删非法行（默认）；flip=负价翻正")
    args = ap.parse_args()

    files = sorted(IDX_DIR.glob("idx_*.parquet"))
    if not files:
        print(f"未找到指数文件：{IDX_DIR}")
        return

    if args.apply:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = BACKUP_ROOT / ts
        backup_dir.mkdir(parents=True, exist_ok=True)
        print(f"[apply] 备份目录：{backup_dir}")
    else:
        print("[dry-run] 仅统计，不修改任何文件（加 --apply 才落盘）")

    tot_dropped = 0
    tot_vol_fixed = 0
    for f in files:
        df = pd.read_parquet(f)
        new_df, dropped, vol_fixed = _repair(df, args.mode)
        tot_dropped += dropped
        tot_vol_fixed += vol_fixed
        if args.apply and (dropped or vol_fixed or len(new_df) != len(df)):
            shutil.copy(f, backup_dir / f.name)
            new_df.to_parquet(f, index=False)
        print(f"  {f.name:32s} rows {len(df):>7} -> {len(new_df):>7} "
              f"| 删 {dropped:>6} | 体积修正 {vol_fixed:>6}")

    print(f"\n合计：文件 {len(files)} | 删除行 {tot_dropped} | 体积修正 {tot_vol_fixed}")
    if args.apply:
        print(f"原文件已备份至：{BACKUP_ROOT}")
    else:
        print("（dry-run 完成，未改动）")


if __name__ == "__main__":
    main()
