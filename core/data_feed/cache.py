"""SQLite 缓存层。

统一缓存键: (symbol, market, interval, date)。
行情与公告分别设置 TTL（见 configs/base.yaml: data_feed.cache）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from core.config import get_config, get_path


class CacheStore:
    """线程安全的 SQLite 缓存。所有数据源共享。"""

    _instance: CacheStore | None = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Path | str | None = None):
        if getattr(self, "_initialized", False):
            return
        if db_path is None:
            db_path = get_path("cache_db")
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._local = threading.local()
        self._initialized = True
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        """每个线程独立连接（sqlite3 连接不可跨线程）。"""
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kline_cache (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                interval TEXT NOT NULL,
                date TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_kline_lookup
                ON kline_cache(symbol, market, interval, date);

            CREATE TABLE IF NOT EXISTS doc_cache (
                cache_key TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                symbol TEXT,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_doc_lookup
                ON doc_cache(kind, symbol);
            """
        )
        conn.commit()

    @staticmethod
    def _hash_key(parts: list[str]) -> str:
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ===== 行情缓存 =====
    def get_kline(
        self,
        symbol: str,
        market: str,
        interval: str,
        date: str,
        limit: int | None = None,
    ) -> pd.DataFrame | None:
        """读单日 K 线缓存；过期或不存在返回 None。

        ``limit`` 参与缓存键——不同条数请求必须独立缓存，否则短请求的
        少量结果会被长请求误命中（历史脏数据即由此产生）。
        """
        cfg = get_config().get("data_feed", {}).get("cache", {})
        ttl = cfg.get("ttl_hours", 12) * 3600
        key = self._hash_key([symbol, market, interval, date, str(limit or "")])
        conn = self._conn()
        row = conn.execute(
            "SELECT payload, created_at FROM kline_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        payload, created_at = row
        if time.time() - created_at > ttl:
            return None
        data = json.loads(payload)
        if not data:
            return None
        df = pd.DataFrame(data)
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
        # 还原真实数据来源（缓存写入时由 _src 列携带，避免 attrs 在 JSON 往返中丢失）
        if "_src" in df.columns:
            df.attrs["_source"] = df["_src"].iloc[0]
            df.drop(columns=["_src"], inplace=True)
        return df

    def set_kline(
        self,
        symbol: str,
        market: str,
        interval: str,
        date: str,
        df: pd.DataFrame,
        limit: int | None = None,
    ) -> None:
        if df.empty:
            return
        key = self._hash_key([symbol, market, interval, date, str(limit or "")])
        payload = df.copy()
        # 持久化真实数据来源：pandas attrs 在 JSON 序列化中会丢失，
        # 缓存命中后将无法还原来源标签，故以临时列携带、读出时还原。
        src = payload.attrs.get("_source")
        if src is not None:
            payload["_src"] = src
        if "datetime" in payload.columns:
            payload["datetime"] = payload["datetime"].astype(str)
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO kline_cache "
            "(cache_key, symbol, market, interval, date, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                symbol,
                market,
                interval,
                date,
                payload.to_json(orient="records"),
                time.time(),
            ),
        )
        conn.commit()

    # ===== 文档缓存（新闻/公告）=====
    def get_docs(
        self, kind: str, symbol: str | None, limit: int | None = None
    ) -> list[dict] | None:
        cfg = get_config().get("data_feed", {}).get("cache", {})
        ttl = cfg.get("announcement_ttl_hours", 24) * 3600
        key = self._hash_key([kind, symbol or "", str(limit or "")])
        conn = self._conn()
        row = conn.execute(
            "SELECT payload, created_at FROM doc_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        payload, created_at = row
        if time.time() - created_at > ttl:
            return None
        return json.loads(payload)

    def set_docs(
        self, kind: str, symbol: str | None, docs: list[dict], limit: int | None = None
    ) -> None:
        key = self._hash_key([kind, symbol or "", str(limit or "")])
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO doc_cache "
            "(cache_key, kind, symbol, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (key, kind, symbol, json.dumps(docs, ensure_ascii=False, default=str), time.time()),
        )
        conn.commit()

    def clear(self) -> None:
        """清空全部缓存。"""
        conn = self._conn()
        conn.executescript("DELETE FROM kline_cache; DELETE FROM doc_cache;")
        conn.commit()


def cache_key_date(ts: datetime | None = None) -> str:
    """生成缓存键中的 date 部分（UTC 日期，便于跨市场统一）。"""
    ts = ts or datetime.now(UTC)
    return ts.strftime("%Y-%m-%d")
