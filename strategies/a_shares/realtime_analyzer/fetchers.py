# -*- coding: utf-8 -*-
"""A 股实时快照抓取（无第三方依赖，纯 urlib）。

移植自 ``trading-master/02-A-stock-realtime-analyzer`` 的 ``scripts/a_share_snapshot.py``：
- 东方财富 push2 实时盘口
- 腾讯 fqkline 日 K 线 + 均线/回报指标
- 上证/深成/创业板指数宽度

仅依赖标准库，离线环境会优雅降级（返回空列表 + 日志警告）。
"""
from __future__ import annotations

import datetime as dt
import json
import re
import statistics
import urllib.parse
import urllib.request

EM_QUOTE_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"
TX_KLINE_API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _http_get_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def normalize_code(code: str) -> str:
    c = code.strip().upper().replace(" ", "")
    if c.startswith("SH") and len(c) == 8 and c[2:].isdigit():
        c = c[2:]
    elif c.startswith("SZ") and len(c) == 8 and c[2:].isdigit():
        c = c[2:]
    if "." in c:
        left, right = c.split(".", 1)
        if left.isdigit() and right in {"SH", "SS", "SZ"}:
            c = left
    if not re.fullmatch(r"\d{6}", c):
        raise ValueError(f"Unsupported code format: {code}")
    return c


def code_to_secid(code6: str) -> str:
    if code6.startswith("6"):
        return "1." + code6
    return "0." + code6


def code_to_tencent_symbol(code6: str) -> str:
    if code6.startswith("6"):
        return "sh" + code6
    return "sz" + code6


def fetch_quotes(codes: list[str]) -> list[dict]:
    if not codes:
        return []
    secids = [code_to_secid(c) for c in codes]
    fields = "f12,f14,f2,f3,f4,f5,f6,f7,f8,f9,f10,f15,f16,f17,f18"
    url = EM_QUOTE_API + "?" + urllib.parse.urlencode(
        {"fltt": "2", "invt": "2", "fields": fields, "secids": ",".join(secids)}
    )
    try:
        obj = _http_get_json(url)
    except Exception:
        return []
    diff = obj.get("data", {}).get("diff", [])
    out = []
    for it in diff:
        out.append(
            {
                "code": str(it.get("f12", "")),
                "name": it.get("f14"),
                "last": it.get("f2"),
                "pct": it.get("f3"),
                "chg": it.get("f4"),
                "open": it.get("f17"),
                "high": it.get("f15"),
                "low": it.get("f16"),
                "prev_close": it.get("f18"),
                "volume": it.get("f5"),
                "amount": it.get("f6"),
                "amplitude": it.get("f7"),
                "turnover": it.get("f8"),
                "pe_ttm": it.get("f9"),
                "volume_ratio": it.get("f10"),
            }
        )
    order = {c: i for i, c in enumerate(codes)}
    out.sort(key=lambda x: order.get(x.get("code"), 9999))
    return out


def fetch_index_baseline() -> list[dict]:
    secids = ["1.000001", "0.399001", "0.399006"]
    fields = "f12,f14,f2,f3,f4,f15,f16,f17,f18,f104,f105,f6,f7"
    url = EM_QUOTE_API + "?" + urllib.parse.urlencode(
        {"fltt": "2", "invt": "2", "fields": fields, "secids": ",".join(secids)}
    )
    try:
        obj = _http_get_json(url)
    except Exception:
        return []
    diff = obj.get("data", {}).get("diff", [])
    out = []
    for it in diff:
        out.append(
            {
                "code": str(it.get("f12", "")),
                "name": it.get("f14"),
                "last": it.get("f2"),
                "pct": it.get("f3"),
                "chg": it.get("f4"),
                "high": it.get("f15"),
                "low": it.get("f16"),
                "open": it.get("f17"),
                "prev_close": it.get("f18"),
                "amount": it.get("f6"),
                "amplitude": it.get("f7"),
                "up_count": it.get("f104"),
                "down_count": it.get("f105"),
            }
        )
    return out


def _ma(vals: list[float], n: int) -> float | None:
    if len(vals) < n:
        return None
    return round(statistics.mean(vals[-n:]), 4)


def _ret(vals: list[float], n: int) -> float | None:
    if len(vals) <= n:
        return None
    base = vals[-(n + 1)]
    if not base:
        return None
    return round((vals[-1] / base - 1) * 100, 4)


def fetch_kline(code6: str, days: int = 60) -> dict:
    symbol = code_to_tencent_symbol(code6)
    url = TX_KLINE_API + "?" + urllib.parse.urlencode(
        {"param": f"{symbol},day,,,{days},qfq"}
    )
    try:
        obj = _http_get_json(url)
    except Exception:
        return {"metrics": {}, "klines": []}
    data = obj.get("data", {}).get(symbol, {})
    rows = data.get("qfqday") or data.get("day") or []

    klines: list[dict] = []
    closes: list[float] = []
    for r in rows:
        try:
            rec = {
                "date": r[0],
                "open": float(r[1]),
                "close": float(r[2]),
                "high": float(r[3]),
                "low": float(r[4]),
                "volume": float(r[5]),
            }
        except Exception:
            continue
        klines.append(rec)
        closes.append(rec["close"])

    metrics = {
        "latest_date": klines[-1]["date"] if klines else None,
        "close": closes[-1] if closes else None,
        "ret_5d_pct": _ret(closes, 5),
        "ret_10d_pct": _ret(closes, 10),
        "ret_20d_pct": _ret(closes, 20),
        "ma5": _ma(closes, 5),
        "ma10": _ma(closes, 10),
        "ma20": _ma(closes, 20),
        "high_10d": max(closes[-10:]) if len(closes) >= 10 else (max(closes) if closes else None),
        "low_10d": min(closes[-10:]) if len(closes) >= 10 else (min(closes) if closes else None),
    }
    return {"metrics": metrics, "klines": klines}


EM_SUGGEST_API = "https://searchapi.eastmoney.com/api/suggest/get"


def search_stock_by_name(keyword: str, count: int = 8) -> list[tuple[str, str]]:
    url = EM_SUGGEST_API + "?" + urllib.parse.urlencode(
        {
            "input": keyword,
            "type": "14",
            "token": "D43BF722C8E33BDC906FB84D85E326A8",
            "count": count,
        }
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("utf-8", "ignore")
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return []
        obj = json.loads(m.group())
        items = obj.get("QuotationCodeTable", {}).get("Data") or []
        results = []
        for it in items:
            code = str(it.get("Code", ""))
            name = it.get("Name", "")
            sec_type = str(it.get("SecurityType", ""))
            if re.fullmatch(r"\d{6}", code) and sec_type in {"1", "2"}:
                results.append((code, name))
        return results
    except Exception:
        return []


def parse_codes(raw: str) -> list[str]:
    parts = [x for x in re.split(r"[,，\s]+", raw.strip()) if x]
    out: list[str] = []
    for p in parts:
        try:
            c = normalize_code(p)
        except ValueError:
            continue
        if c not in out:
            out.append(c)
    return out
