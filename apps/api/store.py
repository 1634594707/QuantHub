"""轻量应用态持久化层。

职责：策略参数预设、策略运行历史、组合配置。
- 单文件 SQLite（WAL），线程安全，复用 core 既有的 SQLite 模式。
- 与行情缓存（core/data_feed/cache.py）隔离，专供应用业务态。
- 所有写操作幂等、带唯一 id，便于前端乐观更新与回查。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from . import database

_DB = (
    Path(os.environ.get("QUANTHUB_STORE_PATH", Path(__file__).resolve().parent / "store.db"))
    .expanduser()
    .resolve()
)
_lock = threading.Lock()


def _encode_cursor(value: float, record_id: str) -> str:
    payload = json.dumps([value, record_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[float, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding).decode("utf-8"))
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError
        return float(payload[0]), str(payload[1])
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("分页游标无效") from exc


@contextmanager
def _conn() -> Iterator[database.ConnectionAdapter]:
    engine = database.engine_for(_DB)
    with engine.connect() as connection:
        transaction = connection.begin()
        adapter = database.ConnectionAdapter(
            connection,
            postgresql=connection.dialect.name == "postgresql",
        )
        try:
            adapter.execute("PRAGMA journal_mode=WAL")
            adapter.execute("PRAGMA foreign_keys=ON")
            yield adapter
            if transaction.is_active and not adapter.rolled_back:
                transaction.commit()
        except Exception:
            if transaction.is_active:
                transaction.rollback()
            raise


def _ensure_column(
    conn: database.ConnectionAdapter,
    table: str,
    column: str,
    definition: str,
) -> None:
    """Add a column when upgrading an existing database."""
    columns = conn.column_names(table)
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _init() -> None:
    with _lock, _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS strategy_presets (
                id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                name TEXT NOT NULL,
                params TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS strategy_runs (
                id TEXT PRIMARY KEY,
                strategy TEXT NOT NULL,
                params TEXT NOT NULL,
                result TEXT NOT NULL,
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS portfolio_allocs (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                strategy TEXT NOT NULL,
                weight REAL NOT NULL,
                symbol TEXT,
                live INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                ts REAL NOT NULL
            )"""
        )
        # 持仓明细（用户可编辑，落库持久化）
        c.execute(
            """CREATE TABLE IF NOT EXISTS holdings (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                instrument_id TEXT,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                shares REAL NOT NULL,
                cost REAL NOT NULL,
                market TEXT NOT NULL DEFAULT 'a_shares',
                ts REAL NOT NULL
            )"""
        )
        # 关注列表（用户可编辑，落库持久化）
        c.execute(
            """CREATE TABLE IF NOT EXISTS watchlist (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                instrument_id TEXT,
                sym TEXT NOT NULL,
                name TEXT NOT NULL,
                market TEXT NOT NULL DEFAULT 'a_shares',
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )"""
        )
        # 信号中心（策略产出 + 手动发布，重启不丢）
        c.execute(
            """CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                instrument_id TEXT,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                direction TEXT NOT NULL,
                score REAL NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                meta_json TEXT NOT NULL DEFAULT '{}',
                ts_iso TEXT NOT NULL,
                ts_epoch REAL NOT NULL
            )"""
        )
        # 统一标的元数据（Instrument 治理）
        c.execute(
            """CREATE TABLE IF NOT EXISTS instruments (
                code TEXT NOT NULL,
                market TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                currency TEXT NOT NULL DEFAULT '',
                asset_class TEXT NOT NULL DEFAULT 'stock',
                meta TEXT NOT NULL DEFAULT '{}',
                ts REAL NOT NULL,
                PRIMARY KEY (code, market)
            )"""
        )
        # 策略实验室：策略定义、版本、实验、回测运行
        c.execute(
            """CREATE TABLE IF NOT EXISTS strategy_definitions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                strategy_key TEXT NOT NULL,
                market TEXT NOT NULL DEFAULT 'a_shares',
                description TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS strategy_versions (
                id TEXT PRIMARY KEY,
                definition_id TEXT NOT NULL,
                version TEXT NOT NULL,
                params TEXT NOT NULL DEFAULT '{}',
                code_hash TEXT NOT NULL DEFAULT '',
                changelog TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                UNIQUE (definition_id, version),
                FOREIGN KEY (definition_id) REFERENCES strategy_definitions(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY,
                definition_id TEXT NOT NULL,
                version_id TEXT,
                research_run_id TEXT,
                instrument_id TEXT,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT '1d',
                status TEXT NOT NULL DEFAULT 'pending',
                params TEXT NOT NULL DEFAULT '{}',
                note TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                FOREIGN KEY (definition_id) REFERENCES strategy_definitions(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS backtest_runs (
                id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT '1d',
                params TEXT NOT NULL DEFAULT '{}',
                data_snapshot TEXT NOT NULL DEFAULT '{}',
                initial_capital REAL NOT NULL DEFAULT 100000,
                equity_curve TEXT NOT NULL DEFAULT '[]',
                trades TEXT NOT NULL DEFAULT '[]',
                metrics TEXT NOT NULL DEFAULT '{}',
                seed TEXT,
                status TEXT NOT NULL DEFAULT 'succeeded',
                error TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL,
                finished_at REAL,
                FOREIGN KEY (experiment_id) REFERENCES experiments(id)
            )"""
        )
        # 组合账本：成交、现金流水、持仓快照、基准
        c.execute(
            """CREATE TABLE IF NOT EXISTS ledger_trades (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                instrument_id TEXT NOT NULL,
                code TEXT NOT NULL,
                market TEXT NOT NULL,
                direction TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL DEFAULT 0,
                ts REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                note TEXT NOT NULL DEFAULT '',
                strategy_id TEXT,
                strategy_version TEXT,
                factor_key TEXT,
                factor_version TEXT,
                research_run_id TEXT,
                signal_id TEXT,
                simulation_order_id TEXT,
                execution_id TEXT,
                market_regime_id TEXT,
                attribution_status TEXT NOT NULL DEFAULT 'unknown_attribution'
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS ledger_cash (
                id TEXT PRIMARY KEY,
                direction TEXT NOT NULL,
                amount REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'CNY',
                ts REAL NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                note TEXT NOT NULL DEFAULT ''
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS ledger_positions (
                id TEXT PRIMARY KEY,
                instrument_id TEXT NOT NULL,
                code TEXT NOT NULL,
                market TEXT NOT NULL,
                quantity REAL NOT NULL,
                average_cost REAL NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0,
                ts REAL NOT NULL,
                UNIQUE (instrument_id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS ledger_benchmarks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL,
                market TEXT NOT NULL,
                equity_curve TEXT NOT NULL DEFAULT '[]',
                metrics TEXT NOT NULL DEFAULT '{}',
                ts REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS ledger_corrections (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                before_json TEXT NOT NULL,
                after_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS data_source_incidents (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT NOT NULL,
                started_at REAL NOT NULL,
                recovered_at REAL,
                acknowledged_at REAL,
                resolution TEXT,
                last_check_json TEXT,
                updated_at REAL NOT NULL,
                UNIQUE (source, operation, started_at)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS research_incidents (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT NOT NULL,
                research_run_id TEXT,
                context_json TEXT NOT NULL DEFAULT '{}',
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (kind, fingerprint, status)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS roles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS permissions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS user_roles (
                user_id TEXT NOT NULL,
                role_id TEXT NOT NULL,
                PRIMARY KEY (user_id, role_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (role_id) REFERENCES roles(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS role_permissions (
                role_id TEXT NOT NULL,
                permission_id TEXT NOT NULL,
                PRIMARY KEY (role_id, permission_id),
                FOREIGN KEY (role_id) REFERENCES roles(id),
                FOREIGN KEY (permission_id) REFERENCES permissions(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS api_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                expires_at REAL,
                last_used_at REAL,
                created_at REAL NOT NULL,
                revoked_at REAL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                result TEXT NOT NULL,
                error TEXT,
                created_at REAL NOT NULL
            )"""
        )
        permissions = (
            "read",
            # 交易执行权限：只授予 admin / operator，reviewer 只能审信号不能下单。
            "trading.write",
            "signals.write",
            "ledger.write",
            "strategy.write",
            "simulation.write",
            "research.write",
            "portfolio.write",
            "automation.manage",
            "backups.manage",
            "config.manage",
            "users.manage",
        )
        roles = ("admin", "operator", "reviewer", "viewer")
        for name in permissions:
            c.execute("INSERT OR IGNORE INTO permissions (id, name) VALUES (?, ?)", (name, name))
        for name in roles:
            c.execute("INSERT OR IGNORE INTO roles (id, name) VALUES (?, ?)", (name, name))
        role_grants = {
            "admin": permissions,
            "operator": tuple(name for name in permissions if name != "users.manage"),
            "reviewer": ("read", "signals.write", "research.write"),
            "viewer": ("read",),
        }
        for role, grants in role_grants.items():
            for permission in grants:
                c.execute(
                    "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                    (role, permission),
                )
        c.execute(
            """INSERT OR IGNORE INTO users (id, username, display_name, active, created_at)
               VALUES ('local-user', 'local-user', 'Local Administrator', 1, ?)""",
            (time.time(),),
        )
        c.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES ('local-user', 'admin')"
        )
        _ensure_column(c, "signals", "status", "TEXT NOT NULL DEFAULT 'new'")
        _ensure_column(c, "signals", "expires_at", "REAL")
        _ensure_column(c, "signals", "reviewed_at", "REAL")
        _ensure_column(c, "signals", "decision_note", "TEXT")
        _ensure_column(c, "signals", "order_id", "TEXT")
        _ensure_column(c, "signals", "fingerprint", "TEXT")
        _ensure_column(c, "signals", "received_at", "REAL")
        _ensure_column(c, "strategy_definitions", "archived_at", "REAL")
        _ensure_column(c, "strategy_versions", "archived_at", "REAL")
        _ensure_column(c, "experiments", "archived_at", "REAL")
        _ensure_column(c, "experiments", "updated_at", "REAL")
        _ensure_column(c, "experiments", "research_run_id", "TEXT")
        c.execute("UPDATE experiments SET updated_at=created_at WHERE updated_at IS NULL")
        c.execute("UPDATE signals SET received_at=ts_epoch WHERE received_at IS NULL")
        # 研究运行是行情、新闻、PA 与 Ensemble 的统一可追溯容器。
        c.execute(
            """CREATE TABLE IF NOT EXISTS research_runs (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                instrument_id TEXT,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                status TEXT NOT NULL,
                modules_json TEXT NOT NULL DEFAULT '[]',
                input_json TEXT NOT NULL DEFAULT '{}',
                summary_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        _ensure_column(c, "research_runs", "note", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(c, "research_runs", "favorite", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "research_runs", "tags_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(c, "research_runs", "archived_at", "REAL")
        _ensure_column(c, "research_runs", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        _ensure_column(c, "portfolio_allocs", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        _ensure_column(c, "holdings", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        _ensure_column(c, "signals", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        _ensure_column(c, "ledger_trades", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        c.execute(
            """CREATE TABLE IF NOT EXISTS user_research_preferences (
                user_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS research_evidence (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                uri TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                captured_at REAL NOT NULL,
                FOREIGN KEY (run_id) REFERENCES research_runs(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS user_workspace_preferences (
                user_id TEXT PRIMARY KEY,
                profile TEXT NOT NULL DEFAULT 'stock_investor',
                hidden_workspaces_json TEXT NOT NULL DEFAULT '[]',
                hidden_modules_json TEXT NOT NULL DEFAULT '[]',
                pinned_routes_json TEXT NOT NULL DEFAULT '[]',
                default_home TEXT NOT NULL DEFAULT '/',
                default_market TEXT NOT NULL DEFAULT 'a_shares',
                recent_routes_json TEXT NOT NULL DEFAULT '[]',
                version INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS workspace_preference_audit (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                before_json TEXT,
                after_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS financial_statements (
                statement_id TEXT PRIMARY KEY,
                instrument_id TEXT NOT NULL,
                statement_type TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                published_at REAL NOT NULL,
                available_at REAL NOT NULL,
                fetched_at REAL NOT NULL,
                source TEXT NOT NULL,
                revision TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS valuation_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                instrument_id TEXT NOT NULL,
                as_of REAL NOT NULL,
                price_at REAL NOT NULL,
                source TEXT NOT NULL,
                method_version TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS company_events (
                event_id TEXT PRIMARY KEY,
                instrument_id TEXT NOT NULL,
                category TEXT NOT NULL,
                published_at REAL NOT NULL,
                available_at REAL NOT NULL,
                source TEXT NOT NULL,
                revision TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS macro_events (
                event_id TEXT PRIMARY KEY,
                region TEXT NOT NULL,
                category TEXT NOT NULL,
                event_at REAL,
                published_at REAL NOT NULL,
                available_at REAL NOT NULL,
                source TEXT NOT NULL,
                revision TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS instrument_relationships (
                relationship_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                instrument_id TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_key TEXT NOT NULL,
                valid_from REAL NOT NULL,
                valid_to REAL,
                source TEXT NOT NULL,
                revision TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        _ensure_column(
            c, "instrument_relationships", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'"
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS macro_transmissions (
                transmission_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                event_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                relationship_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        _ensure_column(c, "macro_transmissions", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_universes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                market TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_universe_members (
                id TEXT PRIMARY KEY,
                universe_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                effective_to TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                industry TEXT NOT NULL DEFAULT '',
                market_cap REAL,
                beta REAL,
                is_st INTEGER NOT NULL DEFAULT 0,
                listed_at TEXT,
                delisted_at TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (universe_id, symbol, effective_from),
                FOREIGN KEY (universe_id) REFERENCES factor_universes(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_research_plans (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                target_market TEXT NOT NULL,
                budget_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_definitions (
                id TEXT PRIMARY KEY,
                factor_key TEXT NOT NULL,
                version TEXT NOT NULL,
                formula_hash TEXT NOT NULL,
                definition_hash TEXT NOT NULL UNIQUE,
                family TEXT NOT NULL,
                market TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE (factor_key, version)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_candidate_validations (
                id TEXT PRIMARY KEY,
                factor_definition_id TEXT NOT NULL,
                data_fingerprint TEXT NOT NULL,
                report_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (factor_definition_id) REFERENCES factor_definitions(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_experiments (
                id TEXT PRIMARY KEY,
                research_plan_id TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                source TEXT NOT NULL,
                parent_experiment_id TEXT,
                factor_definition_id TEXT NOT NULL,
                candidate_validation_id TEXT NOT NULL,
                target_market TEXT NOT NULL,
                data_start TEXT,
                data_end TEXT,
                parameter_grid_json TEXT NOT NULL DEFAULT '{}',
                parameter_combinations INTEGER NOT NULL DEFAULT 1,
                estimated_compute_units INTEGER NOT NULL DEFAULT 1,
                model_json TEXT NOT NULL DEFAULT '{}',
                prompt_json TEXT NOT NULL DEFAULT '{}',
                proposal_json TEXT NOT NULL DEFAULT '{}',
                pre_registration_json TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE (research_plan_id, attempt_number),
                FOREIGN KEY (parent_experiment_id) REFERENCES factor_experiments(id),
                FOREIGN KEY (research_plan_id) REFERENCES factor_research_plans(id),
                FOREIGN KEY (factor_definition_id) REFERENCES factor_definitions(id),
                FOREIGN KEY (candidate_validation_id) REFERENCES factor_candidate_validations(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_experiment_events (
                id TEXT PRIMARY KEY,
                experiment_id TEXT NOT NULL,
                event_sequence INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                result_json TEXT NOT NULL DEFAULT '{}',
                failure_reason TEXT,
                failure_code TEXT,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                FOREIGN KEY (experiment_id) REFERENCES factor_experiments(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_ai_search_rounds (
                id TEXT PRIMARY KEY,
                research_plan_id TEXT NOT NULL,
                round_id TEXT NOT NULL,
                candidate_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL,
                max_formula_complexity INTEGER NOT NULL,
                llm_tokens INTEGER NOT NULL DEFAULT 0,
                input_fingerprint TEXT NOT NULL,
                approval_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                stop_reason TEXT,
                created_at REAL NOT NULL,
                UNIQUE (research_plan_id, round_id),
                FOREIGN KEY (research_plan_id) REFERENCES factor_research_plans(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_confirmation_set_openings (
                id TEXT PRIMARY KEY,
                research_plan_id TEXT NOT NULL UNIQUE,
                experiment_id TEXT NOT NULL,
                confirmation_data_fingerprint TEXT NOT NULL,
                opened_by TEXT NOT NULL,
                irreversible_ack INTEGER NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (research_plan_id) REFERENCES factor_research_plans(id),
                FOREIGN KEY (experiment_id) REFERENCES factor_experiments(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_lifecycle_events (
                id TEXT PRIMARY KEY,
                factor_definition_id TEXT NOT NULL,
                event_sequence INTEGER NOT NULL,
                state TEXT NOT NULL,
                target_market TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                rule TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                UNIQUE (factor_definition_id, target_market, event_sequence),
                FOREIGN KEY (factor_definition_id) REFERENCES factor_definitions(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS analysis_tasks (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                request_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT,
                error TEXT,
                attempt INTEGER NOT NULL DEFAULT 1,
                parent_task_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                duration_ms INTEGER
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS research_reports (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                research_run_id TEXT NOT NULL,
                task_id TEXT,
                mode TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'queued',
                data_cutoff TEXT,
                model_version TEXT,
                prompt_version TEXT,
                snapshot_json TEXT,
                content_hash TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (research_run_id, mode, version),
                FOREIGN KEY (research_run_id) REFERENCES research_runs(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS research_report_sections (
                id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                section_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                error TEXT,
                updated_at REAL NOT NULL,
                UNIQUE (report_id, section_key),
                FOREIGN KEY (report_id) REFERENCES research_reports(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS research_report_events (
                id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                section_id TEXT,
                event_type TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_version TEXT NOT NULL DEFAULT 'report-stream-v1',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                UNIQUE (report_id, sequence),
                FOREIGN KEY (report_id) REFERENCES research_reports(id) ON DELETE CASCADE,
                FOREIGN KEY (section_id) REFERENCES research_report_sections(id) ON DELETE SET NULL
            )"""
        )
        _ensure_column(c, "analysis_tasks", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        c.execute(
            """CREATE TABLE IF NOT EXISTS simulation_orders (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL DEFAULT 'local-user',
                intent_id TEXT UNIQUE,
                signal_id TEXT UNIQUE,
                account_id TEXT NOT NULL DEFAULT 'paper',
                instrument_id TEXT,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL NOT NULL,
                limit_price REAL,
                status TEXT NOT NULL,
                filled_quantity REAL NOT NULL DEFAULT 0,
                average_price REAL,
                audit_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE SET NULL
            )"""
        )
        _ensure_column(c, "simulation_orders", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        c.execute(
            """CREATE TABLE IF NOT EXISTS simulation_risk_decisions (
                id TEXT PRIMARY KEY,
                intent_id TEXT NOT NULL,
                order_id TEXT,
                account_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                outcome TEXT NOT NULL,
                reason_codes_json TEXT NOT NULL DEFAULT '[]',
                snapshot_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS trading_cost_profiles (
                profile_id TEXT NOT NULL,
                version TEXT NOT NULL,
                market TEXT NOT NULL,
                account_scope TEXT,
                effective_from TEXT,
                effective_to TEXT,
                content_hash TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (profile_id, version)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_universe_versions (
                id TEXT PRIMARY KEY,
                universe_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                parent_version_id TEXT,
                source TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                members_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE (universe_id, version),
                FOREIGN KEY (universe_id) REFERENCES factor_universes(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_universe_batches (
                id TEXT PRIMARY KEY,
                universe_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                diff_json TEXT NOT NULL DEFAULT '{}',
                errors_json TEXT NOT NULL DEFAULT '[]',
                version_id TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (universe_id, idempotency_key),
                FOREIGN KEY (universe_id) REFERENCES factor_universes(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS simulation_executions (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL NOT NULL,
                executed_at REAL NOT NULL,
                ledger_sync_status TEXT NOT NULL DEFAULT 'pending',
                ledger_trade_id TEXT,
                ledger_sync_error TEXT,
                FOREIGN KEY (order_id) REFERENCES simulation_orders(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS automation_job_overrides (
                name TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                cron TEXT NOT NULL,
                updated_at REAL NOT NULL,
                updated_by TEXT NOT NULL DEFAULT 'local-user'
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_research_jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                universe_id TEXT NOT NULL,
                cron TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                request_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                updated_by TEXT NOT NULL DEFAULT 'local-user',
                FOREIGN KEY (universe_id) REFERENCES factor_universes(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_factory_runs (
                id TEXT PRIMARY KEY,
                research_plan_id TEXT NOT NULL,
                status TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                selected_factor_key TEXT,
                selected_factor_version TEXT,
                selected_experiment_id TEXT,
                error TEXT,
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                observation_started_at REAL,
                observation_ends_at REAL,
                UNIQUE (research_plan_id),
                FOREIGN KEY (research_plan_id) REFERENCES factor_research_plans(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_factory_candidates (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                factor_key TEXT NOT NULL,
                factor_version TEXT NOT NULL,
                source TEXT NOT NULL,
                experiment_id TEXT,
                status TEXT NOT NULL,
                rank_order INTEGER,
                metrics_json TEXT NOT NULL DEFAULT '{}',
                gate_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (run_id, factor_key, factor_version),
                FOREIGN KEY (run_id) REFERENCES factor_factory_runs(id) ON DELETE CASCADE,
                FOREIGN KEY (experiment_id) REFERENCES factor_experiments(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS factor_factory_observations (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                observed_at REAL NOT NULL,
                market_time TEXT NOT NULL,
                price REAL NOT NULL,
                signal REAL NOT NULL,
                position_weight REAL NOT NULL,
                gross_return REAL NOT NULL,
                cost REAL NOT NULL,
                net_return REAL NOT NULL,
                equity REAL NOT NULL,
                drawdown REAL NOT NULL,
                fill_rate REAL NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                UNIQUE (run_id, market_time),
                FOREIGN KEY (run_id) REFERENCES factor_factory_runs(id) ON DELETE CASCADE
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS automation_runs (
                id TEXT PRIMARY KEY,
                job_name TEXT NOT NULL,
                status TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 1,
                parent_run_id TEXT,
                log TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL,
                duration_ms INTEGER,
                result_type TEXT,
                result_id TEXT,
                acknowledged_at REAL,
                acknowledged_by TEXT
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS automation_audit_logs (
                id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                actor TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                result TEXT NOT NULL,
                error TEXT,
                created_at REAL NOT NULL
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS alert_rules (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                market TEXT NOT NULL,
                threshold REAL,
                enabled INTEGER NOT NULL DEFAULT 1,
                frequency_minutes INTEGER NOT NULL DEFAULT 15,
                quiet_start TEXT,
                quiet_end TEXT,
                expires_at REAL,
                context_json TEXT NOT NULL DEFAULT '{}',
                last_checked_at REAL,
                last_triggered_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )"""
        )
        c.execute(
            """CREATE TABLE IF NOT EXISTS alert_events (
                id TEXT PRIMARY KEY,
                rule_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                message TEXT NOT NULL,
                observed_value REAL,
                related_type TEXT,
                related_id TEXT,
                delivery_json TEXT NOT NULL DEFAULT '{}',
                triggered_at REAL NOT NULL,
                acknowledged_at REAL,
                FOREIGN KEY (rule_id) REFERENCES alert_rules(id) ON DELETE CASCADE
            )"""
        )
        _ensure_column(
            c,
            "simulation_executions",
            "ledger_sync_status",
            "TEXT NOT NULL DEFAULT 'pending'",
        )
        _ensure_column(c, "simulation_executions", "ledger_trade_id", "TEXT")
        _ensure_column(c, "simulation_executions", "ledger_sync_error", "TEXT")
        _ensure_column(c, "automation_runs", "result_type", "TEXT")
        _ensure_column(c, "automation_runs", "result_id", "TEXT")
        _ensure_column(c, "holdings", "instrument_id", "TEXT")
        _ensure_column(c, "watchlist", "instrument_id", "TEXT")
        _ensure_column(c, "watchlist", "owner_id", "TEXT NOT NULL DEFAULT 'local-user'")
        c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_owner_ts ON watchlist(owner_id, ts)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_allocs_owner ON portfolio_allocs(owner_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_holdings_owner ON holdings(owner_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_signals_owner ON signals(owner_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ledger_owner ON ledger_trades(owner_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_simorders_owner ON simulation_orders(owner_id)")
        _ensure_column(c, "signals", "instrument_id", "TEXT")
        _ensure_column(c, "research_runs", "instrument_id", "TEXT")
        _ensure_column(c, "experiments", "instrument_id", "TEXT")
        _ensure_column(c, "simulation_orders", "instrument_id", "TEXT")
        _ensure_column(c, "simulation_orders", "audit_json", "TEXT NOT NULL DEFAULT '{}' ")
        _ensure_column(c, "simulation_orders", "intent_id", "TEXT")
        _ensure_column(c, "factor_universes", "current_version_id", "TEXT")
        for column in (
            "strategy_id",
            "strategy_version",
            "factor_key",
            "factor_version",
            "research_run_id",
            "signal_id",
            "simulation_order_id",
            "execution_id",
            "market_regime_id",
        ):
            _ensure_column(c, "ledger_trades", column, "TEXT")
        _ensure_column(
            c,
            "ledger_trades",
            "attribution_status",
            "TEXT NOT NULL DEFAULT 'unknown_attribution'",
        )
        _ensure_column(
            c,
            "factor_experiments",
            "proposal_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        _ensure_column(
            c,
            "factor_experiment_events",
            "event_sequence",
            "INTEGER NOT NULL DEFAULT 0",
        )
        _ensure_column(c, "factor_experiment_events", "failure_code", "TEXT")
        _ensure_column(
            c,
            "factor_experiments",
            "estimated_compute_units",
            "INTEGER NOT NULL DEFAULT 1",
        )
        _ensure_column(c, "factor_experiments", "candidate_validation_id", "TEXT")
        _ensure_column(
            c,
            "factor_ai_search_rounds",
            "approval_json",
            "TEXT NOT NULL DEFAULT '{}'",
        )
        c.execute(
            "UPDATE holdings SET instrument_id=market || ':' || UPPER(code) WHERE instrument_id IS NULL"
        )
        c.execute(
            "UPDATE watchlist SET instrument_id=market || ':' || UPPER(sym) WHERE instrument_id IS NULL"
        )
        c.execute(
            "UPDATE signals SET instrument_id=market || ':' || UPPER(symbol) WHERE instrument_id IS NULL"
        )
        c.execute(
            "UPDATE research_runs SET instrument_id=market || ':' || UPPER(symbol) WHERE instrument_id IS NULL"
        )
        c.execute(
            "UPDATE experiments SET instrument_id=market || ':' || UPPER(symbol) WHERE instrument_id IS NULL"
        )
        c.execute(
            "UPDATE simulation_orders SET instrument_id=market || ':' || UPPER(symbol) WHERE instrument_id IS NULL"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_presets_strategy ON strategy_presets(strategy)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_runs_strategy ON strategy_runs(strategy)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_allocs_strategy ON portfolio_allocs(strategy)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_holdings_market ON holdings(market)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_holdings_instrument ON holdings(instrument_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_market ON watchlist(market)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_instrument ON watchlist(instrument_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_signals_epoch ON signals(ts_epoch)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_signals_instrument ON signals(instrument_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_signals_fingerprint ON signals(fingerprint)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_research_symbol ON research_runs(symbol)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_research_owner ON research_runs(owner_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_research_updated ON research_runs(updated_at)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_research_favorite ON research_runs(favorite)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_research_archived ON research_runs(archived_at)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_research_jobs_enabled "
            "ON factor_research_jobs(enabled)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_factory_runs_status "
            "ON factor_factory_runs(status, updated_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_factory_candidates_run "
            "ON factor_factory_candidates(run_id, rank_order)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_factory_observations_run "
            "ON factor_factory_observations(run_id, observed_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_instrument ON research_runs(instrument_id)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_evidence_run ON research_evidence(run_id)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_financial_statement_pit "
            "ON financial_statements(instrument_id, statement_type, period_end, available_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_valuation_snapshot_pit "
            "ON valuation_snapshots(instrument_id, as_of)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_company_events_instrument_time "
            "ON company_events(instrument_id, available_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_macro_events_region_time "
            "ON macro_events(region, available_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_relationships_instrument_time "
            "ON instrument_relationships(owner_id, instrument_id, valid_from, valid_to)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_transmissions_owner_instrument_event "
            "ON macro_transmissions(owner_id, instrument_id, event_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_universe_market ON factor_universes(market)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_members_universe "
            "ON factor_universe_members(universe_id, effective_from, effective_to)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_research_plans_market "
            "ON factor_research_plans(target_market)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_definitions_formula "
            "ON factor_definitions(formula_hash, family)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_candidate_validations_definition "
            "ON factor_candidate_validations(factor_definition_id, created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_experiments_plan "
            "ON factor_experiments(research_plan_id, attempt_number)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_experiment_events_experiment "
            "ON factor_experiment_events(experiment_id, created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_lifecycle_definition_market "
            "ON factor_lifecycle_events(factor_definition_id, target_market, event_sequence)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_ai_search_rounds_plan "
            "ON factor_ai_search_rounds(research_plan_id, created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_factor_confirmation_openings_experiment "
            "ON factor_confirmation_set_openings(experiment_id)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_analysis_tasks_owner ON analysis_tasks(owner_id)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_analysis_tasks_fingerprint "
            "ON analysis_tasks(fingerprint)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_status ON simulation_orders(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_symbol ON simulation_orders(symbol)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_orders_instrument ON simulation_orders(instrument_id)"
        )
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_orders_intent ON simulation_orders(intent_id) "
            "WHERE intent_id IS NOT NULL"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_executions_order ON simulation_executions(order_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_executions_ledger_sync "
            "ON simulation_executions(ledger_sync_status)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_sim_risk_intent "
            "ON simulation_risk_decisions(intent_id, created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_ledger_factor "
            "ON ledger_trades(factor_key, factor_version, research_run_id)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_universe_versions "
            "ON factor_universe_versions(universe_id, version)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_automation_runs_job ON automation_runs(job_name)")
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_runs_status ON automation_runs(status)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_automation_audit_created "
            "ON automation_audit_logs(created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_ledger_corrections_entity "
            "ON ledger_corrections(entity_type, entity_id, created_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_data_source_incidents_status "
            "ON data_source_incidents(status, updated_at)"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_incidents_status "
            "ON research_incidents(status, updated_at)"
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at)")


if os.environ.get("QUANTHUB_SKIP_STORE_INIT") != "1":
    _init()


def _now() -> float:
    return time.time()


def _instrument_id(code: str, market: str) -> str:
    return f"{market}:{code.strip().upper()}"


# ---------------------------------------------------------------------------
# 预设 presets
# ---------------------------------------------------------------------------
def list_presets() -> dict[str, list[dict]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, strategy, name, params, ts FROM strategy_presets ORDER BY ts DESC"
        ).fetchall()
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["strategy"], []).append(
            {"id": r["id"], "name": r["name"], "params": json.loads(r["params"])}
        )
    return out


def save_preset(strategy: str, name: str, params: dict) -> dict:
    pid = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO strategy_presets (id, strategy, name, params, ts) VALUES (?,?,?,?,?)",
            (pid, strategy, name, json.dumps(params, ensure_ascii=False), _now()),
        )
    return {"id": pid, "name": name, "params": params}


def delete_preset(strategy: str, pid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM strategy_presets WHERE id=? AND strategy=?", (pid, strategy))


# ---------------------------------------------------------------------------
# 运行历史 runs
# ---------------------------------------------------------------------------
def list_runs(limit: int = 500) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, strategy, params, result, ts FROM strategy_runs ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["strategy"],
            "params": json.loads(r["params"]),
            "result": json.loads(r["result"]),
            "ts": r["ts"],
        }
        for r in rows
    ]


def add_run(strategy: str, params: dict, result: dict) -> dict:
    rid = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO strategy_runs (id, strategy, params, result, ts) VALUES (?,?,?,?,?)",
            (
                rid,
                strategy,
                json.dumps(params, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return {"id": rid, "name": strategy, "params": params, "result": result, "ts": _now()}


def clear_runs() -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM strategy_runs")


# ---------------------------------------------------------------------------
# 组合配置 portfolio
# ---------------------------------------------------------------------------
def list_allocs() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, strategy, weight, symbol, live, note, ts FROM portfolio_allocs ORDER BY ts DESC"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "strategy": r["strategy"],
            "weight": r["weight"],
            "symbol": r["symbol"],
            "live": bool(r["live"]),
            "note": r["note"],
        }
        for r in rows
    ]


def save_alloc(
    strategy: str, weight: float, symbol: str | None, live: bool, note: str | None
) -> dict:
    aid = uuid.uuid4().hex[:12]
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO portfolio_allocs (id, strategy, weight, symbol, live, note, ts) VALUES (?,?,?,?,?,?,?)",
            (aid, strategy, float(weight), symbol, int(bool(live)), note, _now()),
        )
    return {
        "id": aid,
        "strategy": strategy,
        "weight": float(weight),
        "symbol": symbol,
        "live": bool(live),
        "note": note,
    }


def delete_alloc(aid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM portfolio_allocs WHERE id=?", (aid,))


def update_alloc_live(aid: str, live: bool) -> None:
    with _lock, _conn() as c:
        c.execute("UPDATE portfolio_allocs SET live=? WHERE id=?", (int(bool(live)), aid))


# ---------------------------------------------------------------------------
# 持仓明细 holdings（用户可编辑，落库持久化；YAML 仅作首次播种）
# ---------------------------------------------------------------------------
def list_holdings() -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, instrument_id, code, name, shares, cost, market, ts FROM holdings ORDER BY ts ASC"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "instrument_id": r["instrument_id"],
            "code": r["code"],
            "name": r["name"],
            "shares": float(r["shares"]),
            "cost": float(r["cost"]),
            "market": r["market"],
        }
        for r in rows
    ]


def add_holding(
    code: str,
    name: str,
    shares: float,
    cost: float,
    market: str = "a_shares",
    instrument_id: str | None = None,
) -> dict:
    hid = uuid.uuid4().hex[:12]
    resolved_id = instrument_id or _instrument_id(code, market)
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO holdings (id, instrument_id, code, name, shares, cost, market, ts) VALUES (?,?,?,?,?,?,?,?)",
            (hid, resolved_id, code, name, float(shares), float(cost), market, _now()),
        )
    return {
        "id": hid,
        "instrument_id": resolved_id,
        "code": code,
        "name": name,
        "shares": float(shares),
        "cost": float(cost),
        "market": market,
    }


def update_holding(hid: str, patch: dict) -> dict | None:
    """部分更新持仓；允许字段：code/name/shares/cost/market。返回更新后的行或 None。"""
    allowed = ("instrument_id", "code", "name", "shares", "cost", "market")
    sets: list[str] = []
    vals: list = []
    for k in allowed:
        if k in patch:
            sets.append(f"{k}=?")
            v = patch[k]
            vals.append(float(v) if k in ("shares", "cost") else v)
    if not sets:
        return None
    vals.append(hid)
    with _lock, _conn() as c:
        c.execute(f"UPDATE holdings SET {', '.join(sets)} WHERE id=?", vals)
        r = c.execute(
            "SELECT id, instrument_id, code, name, shares, cost, market FROM holdings WHERE id=?",
            (hid,),
        ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"],
        "instrument_id": r["instrument_id"],
        "code": r["code"],
        "name": r["name"],
        "shares": float(r["shares"]),
        "cost": float(r["cost"]),
        "market": r["market"],
    }


def delete_holding(hid: str) -> bool:
    with _lock, _conn() as c:
        cursor = c.execute("DELETE FROM holdings WHERE id=?", (hid,))
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# 关注列表 watchlist（用户可编辑，落库持久化）
# ---------------------------------------------------------------------------
def list_watchlist(*, owner_id: str = "local-user") -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT id, owner_id, instrument_id, sym, name, market, ts
               FROM watchlist WHERE owner_id=? ORDER BY ts ASC""",
            (owner_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "owner_id": r["owner_id"],
            "instrument_id": r["instrument_id"],
            "sym": r["sym"],
            "name": r["name"],
            "market": r["market"],
        }
        for r in rows
    ]


def add_watchlist(
    sym: str,
    name: str,
    market: str = "a_shares",
    instrument_id: str | None = None,
    *,
    owner_id: str = "local-user",
) -> dict:
    wid = uuid.uuid4().hex[:12]
    resolved_id = instrument_id or _instrument_id(sym, market)
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO watchlist
               (id, owner_id, instrument_id, sym, name, market, ts)
               VALUES (?,?,?,?,?,?,?)""",
            (wid, owner_id, resolved_id, sym, name, market, _now()),
        )
    return {
        "id": wid,
        "owner_id": owner_id,
        "instrument_id": resolved_id,
        "sym": sym,
        "name": name,
        "market": market,
    }


def update_watchlist(wid: str, patch: dict, *, owner_id: str = "local-user") -> dict | None:
    allowed = ("instrument_id", "sym", "name", "market")
    sets: list[str] = []
    vals: list = []
    for k in allowed:
        if k in patch:
            sets.append(f"{k}=?")
            vals.append(patch[k])
    if not sets:
        return None
    vals.append(wid)
    with _lock, _conn() as c:
        vals.append(owner_id)
        c.execute(f"UPDATE watchlist SET {', '.join(sets)} WHERE id=? AND owner_id=?", vals)
        r = c.execute(
            """SELECT id, owner_id, instrument_id, sym, name, market
               FROM watchlist WHERE id=? AND owner_id=?""",
            (wid, owner_id),
        ).fetchone()
    if r is None:
        return None
    return {
        "id": r["id"],
        "owner_id": r["owner_id"],
        "instrument_id": r["instrument_id"],
        "sym": r["sym"],
        "name": r["name"],
        "market": r["market"],
    }


def delete_watchlist(wid: str, *, owner_id: str = "local-user") -> bool:
    with _lock, _conn() as c:
        cursor = c.execute("DELETE FROM watchlist WHERE id=? AND owner_id=?", (wid, owner_id))
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# 信号中心 signals（策略产出 + 手动发布，重启不丢）
# ---------------------------------------------------------------------------
def add_signal(sig: dict) -> dict:
    """将 signal dict（含 ts 为 ISO 字符串）写入 DB，返回带 id 的 dict。"""
    sid = uuid.uuid4().hex[:12]
    ts_iso = str(sig.get("ts") or "")
    try:
        ts_epoch = datetime.fromisoformat(ts_iso).timestamp()
    except (ValueError, TypeError):
        ts_epoch = _now()
    fingerprint_raw = "|".join(
        str(sig.get(key, "")) for key in ("symbol", "market", "timeframe", "direction", "source")
    )
    fingerprint = hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()
    now = _now()
    expires_in = float(sig.get("meta", {}).get("expires_in_seconds", 86400))
    expires_at = ts_epoch + max(60.0, expires_in)
    instrument_id = str(
        sig.get("instrument_id") or _instrument_id(str(sig["symbol"]), str(sig["market"]))
    )
    with _lock, _conn() as c:
        duplicate = c.execute(
            """SELECT * FROM signals
               WHERE fingerprint=? AND received_at>=?
               ORDER BY received_at DESC LIMIT 1""",
            (fingerprint, now - 300),
        ).fetchone()
        if duplicate is not None:
            return {**_signal_row_dict(duplicate), "deduplicated": True}
        c.execute(
            """INSERT INTO signals
               (id, instrument_id, symbol, market, timeframe, direction, score, confidence, source,
                tags_json, meta_json, ts_iso, ts_epoch, status, expires_at, fingerprint,
                received_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid,
                instrument_id,
                str(sig["symbol"]),
                str(sig["market"]),
                str(sig["timeframe"]),
                str(sig["direction"]),
                float(sig["score"]),
                float(sig["confidence"]),
                str(sig["source"]),
                json.dumps(sig.get("tags", []), ensure_ascii=False),
                json.dumps(sig.get("meta", {}), ensure_ascii=False, default=str),
                ts_iso,
                ts_epoch,
                "new",
                expires_at,
                fingerprint,
                now,
            ),
        )
    return {
        **sig,
        "id": sid,
        "instrument_id": instrument_id,
        "status": "new",
        "expires_at": expires_at,
        "reviewed_at": None,
        "decision_note": None,
        "order_id": None,
        "deduplicated": False,
    }


def _signal_row_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "instrument_id": row["instrument_id"],
        "symbol": row["symbol"],
        "market": row["market"],
        "timeframe": row["timeframe"],
        "direction": row["direction"],
        "score": float(row["score"]),
        "confidence": float(row["confidence"]),
        "source": row["source"],
        "tags": json.loads(row["tags_json"]),
        "meta": json.loads(row["meta_json"]),
        "ts": row["ts_iso"],
        "status": row["status"],
        "expires_at": float(row["expires_at"]) if row["expires_at"] is not None else None,
        "reviewed_at": float(row["reviewed_at"]) if row["reviewed_at"] is not None else None,
        "decision_note": row["decision_note"],
        "order_id": row["order_id"],
    }


def list_signals(
    limit: int = 1000,
    source: str | None = None,
    market: str | None = None,
    status: str | None = None,
) -> list[dict]:
    return list_signals_page(
        limit=limit,
        source=source,
        market=market,
        status=status,
    )["items"]


def list_signals_page(
    limit: int = 1000,
    source: str | None = None,
    market: str | None = None,
    status: str | None = None,
    cursor: str | None = None,
) -> dict:
    with _lock, _conn() as c:
        c.execute(
            """UPDATE signals SET status='expired'
               WHERE status='new' AND expires_at IS NOT NULL AND expires_at<=?""",
            (_now(),),
        )
    sql = "SELECT * FROM signals"
    clauses: list[str] = []
    params: list = []
    if source:
        clauses.append("source=?")
        params.append(source)
    if market:
        clauses.append("market=?")
        params.append(market)
    if status:
        clauses.append("status=?")
        params.append(status)
    base_clauses = list(clauses)
    base_params = list(params)
    if cursor:
        cursor_value, cursor_id = _decode_cursor(cursor)
        clauses.append("(ts_epoch<? OR (ts_epoch=? AND id<?))")
        params.extend([cursor_value, cursor_value, cursor_id])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY ts_epoch DESC, id DESC LIMIT ?"
    params.append(limit + 1)
    count_sql = "SELECT COUNT(*) AS total FROM signals"
    if base_clauses:
        count_sql += " WHERE " + " AND ".join(base_clauses)
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
        total_row = c.execute(count_sql, base_params).fetchone()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        _encode_cursor(float(page_rows[-1]["ts_epoch"]), str(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return {
        "items": [_signal_row_dict(row) for row in page_rows],
        "total": int(total_row["total"]),
        "next_cursor": next_cursor,
    }


def get_signal(sid: str) -> dict | None:
    """按主键读取信号，并在读取前应用过期规则。"""
    with _lock, _conn() as c:
        c.execute(
            """UPDATE signals SET status='expired'
               WHERE id=? AND status='new' AND expires_at IS NOT NULL AND expires_at<=?""",
            (sid, _now()),
        )
        row = c.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    return _signal_row_dict(row) if row is not None else None


def update_signal_status(
    sid: str,
    *,
    status: str,
    note: str | None = None,
    order_id: str | None = None,
) -> dict | None:
    now = _now()
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
        if row is None:
            return None
        c.execute(
            """UPDATE signals
               SET status=?, reviewed_at=?, decision_note=?, order_id=? WHERE id=?""",
            (status, now, note, order_id, sid),
        )
        updated = c.execute("SELECT * FROM signals WHERE id=?", (sid,)).fetchone()
    return _signal_row_dict(updated)


def delete_signal(sid: str) -> None:
    with _lock, _conn() as c:
        c.execute("DELETE FROM signals WHERE id=?", (sid,))


def prune_signals(keep: int = 2000) -> None:
    """保留最近 keep 条，删除更早的（防膨胀）。"""
    with _lock, _conn() as c:
        c.execute(
            "DELETE FROM signals WHERE id NOT IN "
            "(SELECT id FROM signals ORDER BY ts_epoch DESC LIMIT ?)",
            (keep,),
        )


# ---------------------------------------------------------------------------
# 模拟订单与成交（研究模式，不连接真实券商）
# ---------------------------------------------------------------------------
def _execution_row_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "quantity": float(row["quantity"]),
        "price": float(row["price"]),
        "fee": float(row["fee"]),
        "executed_at": float(row["executed_at"]),
        "ledger_sync_status": row["ledger_sync_status"],
        "ledger_trade_id": row["ledger_trade_id"],
        "ledger_sync_error": row["ledger_sync_error"],
    }


def _simulation_order_dict(row: sqlite3.Row, executions: list[dict] | None = None) -> dict:
    audit = json.loads(row["audit_json"] or "{}")
    theoretical_price = audit.get("theoretical_price")
    if theoretical_price is not None:
        theoretical_price = float(theoretical_price)
    for execution in executions or []:
        execution["theoretical_price"] = theoretical_price
        execution["simulated_price"] = float(execution["price"])
        execution["slippage_bps"] = (
            round(
                ((float(execution["price"]) - theoretical_price) / theoretical_price)
                * 10_000
                * (1 if row["side"] == "buy" else -1),
                4,
            )
            if theoretical_price and theoretical_price > 0
            else None
        )
        execution["signal_time"] = audit.get("signal_time")
        execution["tradable_time"] = audit.get("tradable_time")
        execution["rejection_reason"] = audit.get("rejection_reason")
        execution["capacity_used"] = float(audit.get("capacity_used") or 0.0)
        execution["live_trading_enabled"] = False
    return {
        "id": row["id"],
        "intent_id": row["intent_id"],
        "signal_id": row["signal_id"],
        "account_id": row["account_id"],
        "instrument_id": row["instrument_id"],
        "symbol": row["symbol"],
        "market": row["market"],
        "side": row["side"],
        "order_type": row["order_type"],
        "quantity": float(row["quantity"]),
        "limit_price": float(row["limit_price"]) if row["limit_price"] is not None else None,
        "status": row["status"],
        "filled_quantity": float(row["filled_quantity"]),
        "average_price": (
            float(row["average_price"]) if row["average_price"] is not None else None
        ),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "audit": {**audit, "live_trading_enabled": False},
        "executions": executions or [],
    }


def create_simulation_order(
    *,
    symbol: str,
    market: str,
    side: str,
    order_type: str,
    quantity: float,
    limit_price: float | None = None,
    signal_id: str | None = None,
    account_id: str = "paper",
    instrument_id: str | None = None,
    audit: dict[str, Any] | None = None,
    intent_id: str | None = None,
) -> dict:
    """创建模拟订单；关联信号时在同一事务中完成 converted 状态流转。"""
    order_id = f"SIM-{uuid.uuid4().hex[:12].upper()}"
    now = _now()
    resolved_id = instrument_id or _instrument_id(symbol, market)
    with _lock, _conn() as c:
        if signal_id is not None:
            signal = c.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
            if signal is None:
                raise KeyError(signal_id)
            if signal["status"] != "accepted":
                raise ValueError("只有已接受的信号可以转为模拟订单")
        try:
            c.execute(
                """INSERT INTO simulation_orders
                   (id, intent_id, signal_id, account_id, instrument_id, symbol, market, side, order_type,
                   quantity, limit_price, status, filled_quantity, average_price, audit_json,
                   created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',0,NULL,?,?,?)""",
                (
                    order_id,
                    intent_id,
                    signal_id,
                    account_id,
                    resolved_id,
                    symbol,
                    market,
                    side,
                    order_type,
                    float(quantity),
                    float(limit_price) if limit_price is not None else None,
                    json.dumps(
                        {**(audit or {}), "live_trading_enabled": False},
                        ensure_ascii=False,
                        default=str,
                    ),
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("该信号已经关联模拟订单") from exc
        if signal_id is not None:
            c.execute(
                """UPDATE signals
                   SET status='converted', reviewed_at=?, order_id=? WHERE id=?""",
                (now, order_id, signal_id),
            )
        row = c.execute("SELECT * FROM simulation_orders WHERE id=?", (order_id,)).fetchone()
    return _simulation_order_dict(row)


def get_simulation_order(order_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM simulation_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            return None
        executions = c.execute(
            "SELECT * FROM simulation_executions WHERE order_id=? ORDER BY executed_at ASC",
            (order_id,),
        ).fetchall()
    return _simulation_order_dict(row, [_execution_row_dict(item) for item in executions])


def get_simulation_order_by_intent(intent_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM simulation_orders WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if row is None:
            return None
        executions = c.execute(
            "SELECT * FROM simulation_executions WHERE order_id=? ORDER BY executed_at ASC",
            (row["id"],),
        ).fetchall()
    return _simulation_order_dict(row, [_execution_row_dict(item) for item in executions])


def add_simulation_risk_decision(
    *,
    intent_id: str,
    order_id: str | None,
    account_id: str,
    symbol: str,
    market: str,
    outcome: str,
    reason_codes: list[str],
    snapshot: dict[str, Any],
    decision: dict[str, Any],
    input_fingerprint: str,
    rule_version: str,
) -> dict:
    decision_id = f"RISK-{uuid.uuid4().hex[:16].upper()}"
    created_at = _now()
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO simulation_risk_decisions
               (id, intent_id, order_id, account_id, symbol, market, outcome,
                reason_codes_json, snapshot_json, decision_json, input_fingerprint,
                rule_version, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                decision_id,
                intent_id,
                order_id,
                account_id,
                symbol,
                market,
                outcome,
                json.dumps(reason_codes, ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False, default=str),
                json.dumps(decision, ensure_ascii=False, default=str),
                input_fingerprint,
                rule_version,
                created_at,
            ),
        )
    return {
        "id": decision_id,
        "intent_id": intent_id,
        "order_id": order_id,
        "account_id": account_id,
        "symbol": symbol,
        "market": market,
        "outcome": outcome,
        "reason_codes": reason_codes,
        "snapshot": snapshot,
        "decision": decision,
        "input_fingerprint": input_fingerprint,
        "rule_version": rule_version,
        "created_at": created_at,
    }


def update_simulation_risk_order(decision_id: str, order_id: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE simulation_risk_decisions SET order_id=? WHERE id=?",
            (order_id, decision_id),
        )


def list_simulation_risk_decisions(intent_id: str | None = None, limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM simulation_risk_decisions"
    params: list[Any] = []
    if intent_id:
        sql += " WHERE intent_id=?"
        params.append(intent_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [
        {
            "id": row["id"],
            "intent_id": row["intent_id"],
            "order_id": row["order_id"],
            "account_id": row["account_id"],
            "symbol": row["symbol"],
            "market": row["market"],
            "outcome": row["outcome"],
            "reason_codes": json.loads(row["reason_codes_json"] or "[]"),
            "snapshot": json.loads(row["snapshot_json"] or "{}"),
            "decision": json.loads(row["decision_json"] or "{}"),
            "input_fingerprint": row["input_fingerprint"],
            "rule_version": row["rule_version"],
            "created_at": float(row["created_at"]),
        }
        for row in rows
    ]


def save_trading_cost_profile(snapshot: dict[str, Any]) -> dict:
    profile_id = str(snapshot["profile_id"])
    version = str(snapshot["version"])
    content_hash = str(snapshot["content_hash"])
    now = _now()
    serialized = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    with _lock, _conn() as c:
        existing = c.execute(
            "SELECT * FROM trading_cost_profiles WHERE profile_id=? AND version=?",
            (profile_id, version),
        ).fetchone()
        if existing is not None:
            if existing["content_hash"] != content_hash:
                raise ValueError("成本档案版本已存在且内容不可修改")
        else:
            c.execute(
                """INSERT INTO trading_cost_profiles
                   (profile_id, version, market, account_scope, effective_from,
                    effective_to, content_hash, snapshot_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    profile_id,
                    version,
                    snapshot["market"],
                    snapshot.get("account_scope"),
                    snapshot.get("effective_from"),
                    snapshot.get("effective_to"),
                    content_hash,
                    serialized,
                    now,
                ),
            )
    return snapshot


def get_trading_cost_profile(profile_id: str, version: str | None = None) -> dict | None:
    with _lock, _conn() as c:
        if version:
            row = c.execute(
                "SELECT * FROM trading_cost_profiles WHERE profile_id=? AND version=?",
                (profile_id, version),
            ).fetchone()
        else:
            row = c.execute(
                """SELECT * FROM trading_cost_profiles WHERE profile_id=?
                   ORDER BY version DESC, created_at DESC LIMIT 1""",
                (profile_id,),
            ).fetchone()
    return json.loads(row["snapshot_json"]) if row else None


def list_trading_cost_profiles(
    *, market: str | None = None, account_scope: str | None = None
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if market:
        clauses.append("market=?")
        params.append(market)
    if account_scope:
        clauses.append("(account_scope IS NULL OR account_scope=?)")
        params.append(account_scope)
    sql = "SELECT * FROM trading_cost_profiles"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY market, profile_id, version DESC"
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [json.loads(row["snapshot_json"]) for row in rows]


def list_simulation_orders(
    *,
    status: str | None = None,
    symbol: str | None = None,
    account_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    return list_simulation_orders_page(
        status=status,
        symbol=symbol,
        account_id=account_id,
        limit=limit,
    )["items"]


def list_simulation_orders_page(
    *,
    status: str | None = None,
    symbol: str | None = None,
    account_id: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    sql = "SELECT * FROM simulation_orders"
    clauses: list[str] = []
    params: list = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if symbol:
        clauses.append("symbol=?")
        params.append(symbol)
    if account_id:
        clauses.append("account_id=?")
        params.append(account_id)
    base_clauses = list(clauses)
    base_params = list(params)
    if cursor:
        cursor_value, cursor_id = _decode_cursor(cursor)
        clauses.append("(created_at<? OR (created_at=? AND id<?))")
        params.extend([cursor_value, cursor_value, cursor_id])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit + 1)
    count_sql = "SELECT COUNT(*) AS total FROM simulation_orders"
    if base_clauses:
        count_sql += " WHERE " + " AND ".join(base_clauses)
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
        total_row = c.execute(count_sql, base_params).fetchone()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        results = []
        for row in page_rows:
            executions = c.execute(
                """SELECT * FROM simulation_executions
                   WHERE order_id=? ORDER BY executed_at ASC""",
                (row["id"],),
            ).fetchall()
            results.append(
                _simulation_order_dict(row, [_execution_row_dict(item) for item in executions])
            )
    next_cursor = (
        _encode_cursor(float(page_rows[-1]["created_at"]), str(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return {"items": results, "total": int(total_row["total"]), "next_cursor": next_cursor}


def fill_simulation_order(
    order_id: str, *, quantity: float, price: float, fee_rate: float
) -> dict | None:
    now = _now()
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM simulation_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            return None
        if row["status"] not in {"pending", "partially_filled"}:
            raise ValueError("当前订单状态不允许成交")
        remaining = float(row["quantity"]) - float(row["filled_quantity"])
        if quantity > remaining + 1e-9:
            raise ValueError(f"成交数量超过剩余数量 {remaining:g}")
        new_filled = float(row["filled_quantity"]) + quantity
        previous_value = float(row["filled_quantity"]) * float(row["average_price"] or 0)
        average_price = (previous_value + quantity * price) / new_filled
        status = "filled" if new_filled >= float(row["quantity"]) - 1e-9 else "partially_filled"
        execution_id = uuid.uuid4().hex[:12]
        c.execute(
            """INSERT INTO simulation_executions
               (id, order_id, quantity, price, fee, executed_at) VALUES (?,?,?,?,?,?)""",
            (execution_id, order_id, quantity, price, quantity * price * fee_rate, now),
        )
        c.execute(
            """UPDATE simulation_orders
               SET status=?, filled_quantity=?, average_price=?, updated_at=? WHERE id=?""",
            (status, new_filled, average_price, now, order_id),
        )
    return get_simulation_order(order_id)


def update_simulation_execution_ledger_sync(
    execution_id: str,
    *,
    status: str,
    ledger_trade_id: str | None = None,
    error: str | None = None,
) -> dict | None:
    """更新模拟成交的账本同步结果，并返回更新后的成交。"""
    with _lock, _conn() as c:
        c.execute(
            """UPDATE simulation_executions
               SET ledger_sync_status=?, ledger_trade_id=?, ledger_sync_error=?
               WHERE id=?""",
            (status, ledger_trade_id, error, execution_id),
        )
        row = c.execute(
            "SELECT * FROM simulation_executions WHERE id=?",
            (execution_id,),
        ).fetchone()
    return _execution_row_dict(row) if row is not None else None


def cancel_simulation_order(
    order_id: str, *, rejection_reason: str = "user_cancelled"
) -> dict | None:
    now = _now()
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM simulation_orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            return None
        if row["status"] not in {"pending", "partially_filled"}:
            raise ValueError("当前订单状态不允许取消")
        audit = json.loads(row["audit_json"] or "{}")
        audit["rejection_reason"] = rejection_reason.strip() or "user_cancelled"
        audit["live_trading_enabled"] = False
        c.execute(
            "UPDATE simulation_orders SET status='cancelled', audit_json=?, updated_at=? WHERE id=?",
            (json.dumps(audit, ensure_ascii=False), now, order_id),
        )
    return get_simulation_order(order_id)


# ---------------------------------------------------------------------------
# 研究运行 research_runs / research_evidence
# ---------------------------------------------------------------------------
def _research_run_dict(row: sqlite3.Row, evidence_count: int | None = None) -> dict:
    result = {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "instrument_id": row["instrument_id"],
        "symbol": row["symbol"],
        "market": row["market"],
        "timeframe": row["timeframe"],
        "status": row["status"],
        "modules": json.loads(row["modules_json"]),
        "input": json.loads(row["input_json"]),
        "summary": json.loads(row["summary_json"]),
        "error": row["error"],
        "note": row["note"],
        "favorite": bool(row["favorite"]),
        "tags": json.loads(row["tags_json"] or "[]"),
        "archived_at": float(row["archived_at"]) if row["archived_at"] is not None else None,
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }
    if evidence_count is not None:
        result["evidence_count"] = int(evidence_count)
    return result


def create_research_run(
    symbol: str,
    market: str,
    timeframe: str,
    modules: list[str],
    input_data: dict,
    instrument_id: str | None = None,
    owner_id: str = "local-user",
) -> dict:
    run_id = uuid.uuid4().hex
    now = _now()
    resolved_id = instrument_id or _instrument_id(symbol, market)
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO research_runs
               (id, owner_id, instrument_id, symbol, market, timeframe, status, modules_json,
                input_json, summary_json, error, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                owner_id,
                resolved_id,
                symbol,
                market,
                timeframe,
                "draft",
                json.dumps(modules, ensure_ascii=False),
                json.dumps(input_data, ensure_ascii=False, default=str),
                "{}",
                None,
                now,
                now,
            ),
        )
        row = c.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone()
    return _research_run_dict(row, evidence_count=0)


def list_research_runs(
    limit: int = 50,
    symbol: str | None = None,
    status: str | None = None,
    favorite: bool | None = None,
    market: str | None = None,
    timeframe: str | None = None,
    created_from: float | None = None,
    created_to: float | None = None,
    factor_limit: int | None = None,
    factor_horizon: int | None = None,
    factor_transaction_cost_bps: float | None = None,
    factor_walk_forward_mode: str | None = None,
    factor_walk_forward_folds: int | None = None,
    owner_id: str | None = None,
) -> list[dict]:
    return list_research_runs_page(
        limit=limit,
        symbol=symbol,
        status=status,
        favorite=favorite,
        market=market,
        timeframe=timeframe,
        created_from=created_from,
        created_to=created_to,
        factor_limit=factor_limit,
        factor_horizon=factor_horizon,
        factor_transaction_cost_bps=factor_transaction_cost_bps,
        factor_walk_forward_mode=factor_walk_forward_mode,
        factor_walk_forward_folds=factor_walk_forward_folds,
        owner_id=owner_id,
    )["items"]


def list_research_runs_page(
    limit: int = 50,
    symbol: str | None = None,
    status: str | None = None,
    favorite: bool | None = None,
    market: str | None = None,
    timeframe: str | None = None,
    created_from: float | None = None,
    created_to: float | None = None,
    factor_limit: int | None = None,
    factor_horizon: int | None = None,
    factor_transaction_cost_bps: float | None = None,
    factor_walk_forward_mode: str | None = None,
    factor_walk_forward_folds: int | None = None,
    cross_section_factor_key: str | None = None,
    tag: str | None = None,
    archived: bool | None = False,
    module: str | None = None,
    cursor: str | None = None,
    owner_id: str | None = None,
) -> dict:
    sql = """SELECT r.*, COUNT(e.id) AS evidence_count
             FROM research_runs r
             LEFT JOIN research_evidence e ON e.run_id = r.id"""
    clauses: list[str] = []
    params: list = []
    if owner_id:
        clauses.append("r.owner_id=?")
        params.append(owner_id)
    if symbol:
        clauses.append("r.symbol=?")
        params.append(symbol)
    if status:
        clauses.append("r.status=?")
        params.append(status)
    if favorite is not None:
        clauses.append("r.favorite=?")
        params.append(1 if favorite else 0)
    if archived is not None:
        clauses.append("r.archived_at IS NOT NULL" if archived else "r.archived_at IS NULL")
    if tag:
        clauses.append("EXISTS (SELECT 1 FROM json_each(r.tags_json) WHERE value=?)")
        params.append(tag)
    if market:
        clauses.append("r.market=?")
        params.append(market)
    if timeframe:
        clauses.append("r.timeframe=?")
        params.append(timeframe)
    if created_from is not None:
        clauses.append("r.created_at>=?")
        params.append(created_from)
    if created_to is not None:
        clauses.append("r.created_at<?")
        params.append(created_to)
    factor_filters = (
        ("$.factor_research.limit", factor_limit),
        ("$.factor_research.horizon", factor_horizon),
        ("$.factor_research.transaction_cost_bps", factor_transaction_cost_bps),
        ("$.factor_research.walk_forward_mode", factor_walk_forward_mode),
        ("$.factor_research.walk_forward_folds", factor_walk_forward_folds),
    )
    for path, value in factor_filters:
        if value is not None:
            clauses.append("json_extract(r.input_json, ?)=?")
            params.extend([path, value])
    if cross_section_factor_key is not None:
        clauses.append(
            "json_extract(r.input_json, '$.cross_sectional_factor_research.factor_key')=?"
        )
        params.append(cross_section_factor_key)
    if module:
        clauses.append("r.modules_json LIKE ?")
        params.append(f'%"{module}"%')
    base_clauses = list(clauses)
    base_params = list(params)
    if cursor:
        cursor_value, cursor_id = _decode_cursor(cursor)
        clauses.append("(r.updated_at<? OR (r.updated_at=? AND r.id<?))")
        params.extend([cursor_value, cursor_value, cursor_id])
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " GROUP BY r.id ORDER BY r.updated_at DESC, r.id DESC LIMIT ?"
    params.append(limit + 1)
    count_sql = "SELECT COUNT(*) AS total FROM research_runs r"
    if base_clauses:
        count_sql += " WHERE " + " AND ".join(base_clauses)
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
        total_row = c.execute(count_sql, base_params).fetchone()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        _encode_cursor(float(page_rows[-1]["updated_at"]), str(page_rows[-1]["id"]))
        if has_more and page_rows
        else None
    )
    return {
        "items": [_research_run_dict(row, row["evidence_count"]) for row in page_rows],
        "total": int(total_row["total"]),
        "next_cursor": next_cursor,
    }


def list_research_evidence(run_id: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT id, run_id, kind, source, title, uri, payload_json, captured_at
               FROM research_evidence WHERE run_id=? ORDER BY captured_at ASC""",
            (run_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "run_id": row["run_id"],
            "kind": row["kind"],
            "source": row["source"],
            "title": row["title"],
            "uri": row["uri"],
            "payload": json.loads(row["payload_json"]),
            "captured_at": float(row["captured_at"]),
        }
        for row in rows
    ]


def get_research_run(run_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM research_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        return None
    result = _research_run_dict(row)
    result["evidence"] = list_research_evidence(run_id)
    result["evidence_count"] = len(result["evidence"])
    return result


def update_research_run(run_id: str, patch: dict) -> dict | None:
    column_map = {
        "status": "status",
        "modules": "modules_json",
        "input": "input_json",
        "summary": "summary_json",
        "error": "error",
        "note": "note",
        "favorite": "favorite",
        "tags": "tags_json",
        "archived": "archived_at",
    }
    sets: list[str] = []
    params: list = []
    for key, column in column_map.items():
        if key not in patch:
            continue
        value = patch[key]
        if key == "favorite":
            value = 1 if value else 0
        if key == "archived":
            value = _now() if value else None
        if key == "tags":
            value = list(
                dict.fromkeys(str(item).strip() for item in (value or []) if str(item).strip())
            )
        if key in {"modules", "input", "summary", "tags"}:
            value = json.dumps(value, ensure_ascii=False, default=str)
        sets.append(f"{column}=?")
        params.append(value)
    if not sets:
        return get_research_run(run_id)
    sets.append("updated_at=?")
    params.extend([_now(), run_id])
    with _lock, _conn() as c:
        cursor = c.execute(
            f"UPDATE research_runs SET {', '.join(sets)} WHERE id=?",
            params,
        )
    if cursor.rowcount == 0:
        return None
    return get_research_run(run_id)


def update_research_runs(run_ids: list[str], patch: dict) -> list[dict]:
    updated: list[dict] = []
    for run_id in run_ids:
        run = update_research_run(run_id, patch)
        if run is not None:
            updated.append(run)
    return updated


def get_user_research_preference(user_id: str) -> dict[str, Any] | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT payload_json FROM user_research_preferences WHERE user_id=?",
            (user_id,),
        ).fetchone()
    return json.loads(row["payload_json"]) if row is not None else None


def save_user_research_preference(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    now = _now()
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO user_research_preferences (user_id, payload_json, updated_at)
               VALUES (?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   payload_json=excluded.payload_json,
                   updated_at=excluded.updated_at""",
            (user_id, serialized, now),
        )
    return payload


def _workspace_preference_dict(row) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "profile": row["profile"],
        "hidden_workspaces": json.loads(row["hidden_workspaces_json"] or "[]"),
        "hidden_modules": json.loads(row["hidden_modules_json"] or "[]"),
        "pinned_routes": json.loads(row["pinned_routes_json"] or "[]"),
        "default_home": row["default_home"],
        "default_market": row["default_market"],
        "recent_routes": json.loads(row["recent_routes_json"] or "[]"),
        "version": int(row["version"]),
        "updated_at": float(row["updated_at"]),
    }


def get_workspace_preference(user_id: str) -> dict[str, Any] | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM user_workspace_preferences WHERE user_id=?", (user_id,)
        ).fetchone()
    return _workspace_preference_dict(row) if row is not None else None


def save_workspace_preference(
    user_id: str, payload: dict[str, Any], *, expected_version: int | None = None
) -> dict[str, Any]:
    now = _now()
    current = get_workspace_preference(user_id)
    if (
        expected_version is not None
        and current is not None
        and current["version"] != expected_version
    ):
        raise ValueError(f"工作台配置版本冲突，当前版本为 {current['version']}")
    version = int(current["version"] + 1) if current else 1
    normalized = {
        "user_id": user_id,
        "profile": str(payload.get("profile") or "stock_investor"),
        "hidden_workspaces": list(
            dict.fromkeys(str(v) for v in payload.get("hidden_workspaces", []) if str(v))
        ),
        "hidden_modules": list(
            dict.fromkeys(str(v) for v in payload.get("hidden_modules", []) if str(v))
        ),
        "pinned_routes": list(
            dict.fromkeys(str(v) for v in payload.get("pinned_routes", []) if str(v))
        ),
        "default_home": str(payload.get("default_home") or "/"),
        "default_market": str(payload.get("default_market") or "a_shares"),
        "recent_routes": list(
            dict.fromkeys(str(v) for v in payload.get("recent_routes", []) if str(v))
        )[:20],
        "version": version,
        "updated_at": now,
    }
    serialized = {**normalized}
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO user_workspace_preferences
               (user_id, profile, hidden_workspaces_json, hidden_modules_json,
                pinned_routes_json, default_home, default_market, recent_routes_json,
                version, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 profile=excluded.profile,
                 hidden_workspaces_json=excluded.hidden_workspaces_json,
                 hidden_modules_json=excluded.hidden_modules_json,
                 pinned_routes_json=excluded.pinned_routes_json,
                 default_home=excluded.default_home,
                 default_market=excluded.default_market,
                 recent_routes_json=excluded.recent_routes_json,
                 version=excluded.version,
                 updated_at=excluded.updated_at""",
            (
                user_id,
                normalized["profile"],
                json.dumps(normalized["hidden_workspaces"], ensure_ascii=False),
                json.dumps(normalized["hidden_modules"], ensure_ascii=False),
                json.dumps(normalized["pinned_routes"], ensure_ascii=False),
                normalized["default_home"],
                normalized["default_market"],
                json.dumps(normalized["recent_routes"], ensure_ascii=False),
                version,
                now,
            ),
        )
        c.execute(
            """INSERT INTO workspace_preference_audit
               (id, user_id, version, before_json, after_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                uuid.uuid4().hex,
                user_id,
                version,
                json.dumps(current, ensure_ascii=False, default=str) if current else None,
                json.dumps(serialized, ensure_ascii=False, default=str),
                now,
            ),
        )
    return serialized


def list_workspace_preference_audit(user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT id, user_id, version, before_json, after_json, created_at
               FROM workspace_preference_audit WHERE user_id=?
               ORDER BY version DESC LIMIT ?""",
            (user_id, max(1, min(limit, 500))),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "version": int(row["version"]),
            "before": json.loads(row["before_json"]) if row["before_json"] else None,
            "after": json.loads(row["after_json"]),
            "created_at": float(row["created_at"]),
        }
        for row in rows
    ]


def add_research_evidence(
    run_id: str,
    kind: str,
    source: str,
    title: str,
    uri: str | None,
    payload: dict,
) -> dict | None:
    evidence_id = uuid.uuid4().hex
    now = _now()
    with _lock, _conn() as c:
        exists = c.execute("SELECT 1 FROM research_runs WHERE id=?", (run_id,)).fetchone()
        if exists is None:
            return None
        c.execute(
            """INSERT INTO research_evidence
               (id, run_id, kind, source, title, uri, payload_json, captured_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                evidence_id,
                run_id,
                kind,
                source,
                title,
                uri,
                json.dumps(payload, ensure_ascii=False, default=str),
                now,
            ),
        )
        c.execute("UPDATE research_runs SET updated_at=? WHERE id=?", (now, run_id))
    return {
        "id": evidence_id,
        "run_id": run_id,
        "kind": kind,
        "source": source,
        "title": title,
        "uri": uri,
        "payload": payload,
        "captured_at": now,
    }


# ---------------------------------------------------------------------------
# 点时财务报表与估值快照
# ---------------------------------------------------------------------------
def save_financial_statement(payload: dict[str, Any]) -> bool:
    provenance = payload["provenance"]
    with _lock, _conn() as c:
        result = c.execute(
            """INSERT OR IGNORE INTO financial_statements
               (statement_id, instrument_id, statement_type, period_start, period_end,
                published_at, available_at, fetched_at, source, revision, content_hash,
                payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload["statement_id"],
                payload["instrument_id"],
                payload["statement_type"],
                payload["period_start"],
                payload["period_end"],
                datetime.fromisoformat(provenance["published_at"]).timestamp(),
                datetime.fromisoformat(provenance["available_at"]).timestamp(),
                datetime.fromisoformat(provenance["fetched_at"]).timestamp(),
                provenance["source"],
                provenance["revision"],
                provenance["content_hash"],
                json.dumps(payload, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return result.rowcount > 0


def list_financial_statements(
    instrument_id: str,
    *,
    available_as_of: datetime,
    statement_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    sql = "SELECT payload_json FROM financial_statements WHERE instrument_id=? AND available_at<=?"
    params: list[Any] = [instrument_id, available_as_of.timestamp()]
    if statement_type:
        sql += " AND statement_type=?"
        params.append(statement_type)
    sql += " ORDER BY period_end DESC, available_at DESC, statement_id DESC LIMIT ?"
    params.append(max(1, min(limit, 2000)))
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def save_valuation_snapshot(payload: dict[str, Any]) -> bool:
    provenance = payload["provenance"]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with _lock, _conn() as c:
        result = c.execute(
            """INSERT OR IGNORE INTO valuation_snapshots
               (snapshot_id, instrument_id, as_of, price_at, source, method_version,
                content_hash, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                payload["snapshot_id"],
                payload["instrument_id"],
                datetime.fromisoformat(payload["as_of"]).timestamp(),
                datetime.fromisoformat(payload["price_at"]).timestamp(),
                provenance["source"],
                payload["method_version"],
                content_hash,
                json.dumps(payload, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return result.rowcount > 0


def list_valuation_snapshots(
    instrument_id: str,
    *,
    as_of: datetime,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT payload_json FROM valuation_snapshots
               WHERE instrument_id=? AND as_of<=?
               ORDER BY as_of DESC, snapshot_id DESC LIMIT ?""",
            (instrument_id, as_of.timestamp(), max(1, min(limit, 2000))),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def save_company_event(payload: dict[str, Any]) -> bool:
    provenance = payload["provenance"]
    with _lock, _conn() as c:
        result = c.execute(
            """INSERT OR IGNORE INTO company_events
               (event_id, instrument_id, category, published_at, available_at, source,
                revision, content_hash, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                payload["event_id"],
                payload["instrument_id"],
                payload["category"],
                datetime.fromisoformat(provenance["published_at"]).timestamp(),
                datetime.fromisoformat(provenance["available_at"]).timestamp(),
                provenance["source"],
                provenance["revision"],
                provenance["content_hash"],
                json.dumps(payload, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return result.rowcount > 0


def list_company_events(
    instrument_id: str, *, available_as_of: datetime, limit: int = 200
) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT payload_json FROM company_events
               WHERE instrument_id=? AND available_at<=?
               ORDER BY available_at DESC, event_id DESC LIMIT ?""",
            (instrument_id, available_as_of.timestamp(), max(1, min(limit, 2000))),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def save_macro_event(payload: dict[str, Any]) -> bool:
    provenance = payload["provenance"]
    event_at = provenance.get("event_at")
    with _lock, _conn() as c:
        result = c.execute(
            """INSERT OR IGNORE INTO macro_events
               (event_id, region, category, event_at, published_at, available_at, source,
                revision, content_hash, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload["event_id"],
                payload["region"],
                payload["category"],
                datetime.fromisoformat(event_at).timestamp() if event_at else None,
                datetime.fromisoformat(provenance["published_at"]).timestamp(),
                datetime.fromisoformat(provenance["available_at"]).timestamp(),
                provenance["source"],
                provenance["revision"],
                provenance["content_hash"],
                json.dumps(payload, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return result.rowcount > 0


def list_macro_events(
    *, available_as_of: datetime, region: str | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    sql = "SELECT payload_json FROM macro_events WHERE available_at<=?"
    params: list[Any] = [available_as_of.timestamp()]
    if region:
        sql += " AND region=?"
        params.append(region)
    sql += " ORDER BY available_at DESC, event_id DESC LIMIT ?"
    params.append(max(1, min(limit, 2000)))
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def save_instrument_relationship(payload: dict[str, Any], *, owner_id: str = "local-user") -> bool:
    provenance = payload["provenance"]
    storage_id = f"{owner_id}:{payload['relationship_id']}"
    with _lock, _conn() as c:
        result = c.execute(
            """INSERT OR IGNORE INTO instrument_relationships
               (relationship_id, owner_id, instrument_id, target_type, target_key, valid_from,
                valid_to, source, revision, content_hash, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                storage_id,
                owner_id,
                payload["instrument_id"],
                payload["target_type"],
                payload["target_key"],
                datetime.fromisoformat(payload["valid_from"]).timestamp(),
                datetime.fromisoformat(payload["valid_to"]).timestamp()
                if payload.get("valid_to")
                else None,
                provenance["source"],
                provenance["revision"],
                provenance["content_hash"],
                json.dumps(payload, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return result.rowcount > 0


def list_instrument_relationships(
    instrument_id: str,
    *,
    as_of: datetime,
    limit: int = 200,
    owner_id: str = "local-user",
) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT payload_json FROM instrument_relationships
               WHERE owner_id=? AND instrument_id=? AND valid_from<=?
                 AND (valid_to IS NULL OR valid_to>?)
               ORDER BY valid_from DESC, relationship_id DESC LIMIT ?""",
            (
                owner_id,
                instrument_id,
                as_of.timestamp(),
                as_of.timestamp(),
                max(1, min(limit, 2000)),
            ),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def save_macro_transmission(payload: dict[str, Any], *, owner_id: str = "local-user") -> bool:
    storage_id = f"{owner_id}:{payload['transmission_id']}"
    with _lock, _conn() as c:
        result = c.execute(
            """INSERT OR IGNORE INTO macro_transmissions
               (transmission_id, owner_id, event_id, instrument_id, relationship_id,
                payload_json, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                storage_id,
                owner_id,
                payload["event_id"],
                payload["instrument_id"],
                payload["relationship_id"],
                json.dumps(payload, ensure_ascii=False, default=str),
                _now(),
            ),
        )
    return result.rowcount > 0


def list_macro_transmissions(
    instrument_id: str, *, limit: int = 200, owner_id: str = "local-user"
) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT payload_json FROM macro_transmissions
               WHERE owner_id=? AND instrument_id=?
               ORDER BY created_at DESC, transmission_id DESC LIMIT ?""",
            (owner_id, instrument_id, max(1, min(limit, 2000))),
        ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


# ---------------------------------------------------------------------------
# 持久化分析任务 analysis_tasks
# ---------------------------------------------------------------------------
def _analysis_task_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "kind": row["kind"],
        "status": row["status"],
        "symbol": row["symbol"],
        "market": row["market"],
        "timeframe": row["timeframe"],
        "fingerprint": row["fingerprint"],
        "request": json.loads(row["request_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"],
        "attempt": int(row["attempt"]),
        "parent_task_id": row["parent_task_id"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "started_at": float(row["started_at"]) if row["started_at"] is not None else None,
        "finished_at": float(row["finished_at"]) if row["finished_at"] is not None else None,
        "duration_ms": int(row["duration_ms"]) if row["duration_ms"] is not None else None,
    }


def create_analysis_task(
    *,
    kind: str,
    symbol: str,
    market: str,
    timeframe: str,
    fingerprint: str,
    request: dict,
    attempt: int = 1,
    parent_task_id: str | None = None,
    owner_id: str = "local-user",
) -> dict:
    task_id = uuid.uuid4().hex
    now = _now()
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO analysis_tasks
               (id, owner_id, kind, status, symbol, market, timeframe, fingerprint, request_json,
                result_json, error, attempt, parent_task_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                owner_id,
                kind,
                "queued",
                symbol,
                market,
                timeframe,
                fingerprint,
                json.dumps(request, ensure_ascii=False, default=str),
                None,
                None,
                attempt,
                parent_task_id,
                now,
                now,
            ),
        )
        row = c.execute("SELECT * FROM analysis_tasks WHERE id=?", (task_id,)).fetchone()
    return _analysis_task_dict(row)


def get_analysis_task(task_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM analysis_tasks WHERE id=?", (task_id,)).fetchone()
    return _analysis_task_dict(row) if row is not None else None


def find_active_analysis_task(fingerprint: str, owner_id: str | None = None) -> dict | None:
    owner_clause = " AND owner_id=?" if owner_id else ""
    params = (fingerprint, owner_id) if owner_id else (fingerprint,)
    with _lock, _conn() as c:
        row = c.execute(
            f"""SELECT * FROM analysis_tasks
               WHERE fingerprint=?{owner_clause} AND status IN ('queued','running')
               ORDER BY created_at DESC LIMIT 1""",
            params,
        ).fetchone()
    return _analysis_task_dict(row) if row is not None else None


def find_recent_analysis_task(
    *,
    kind: str,
    symbol: str,
    market: str,
    timeframe: str,
    since: float,
    owner_id: str | None = None,
) -> dict | None:
    owner_clause = " AND owner_id=?" if owner_id else ""
    params: tuple[Any, ...] = (kind, symbol, market, timeframe, since)
    if owner_id:
        params = (*params, owner_id)
    with _lock, _conn() as c:
        row = c.execute(
            f"""SELECT * FROM analysis_tasks
               WHERE kind=? AND symbol=? AND market=? AND timeframe=? AND created_at>=?{owner_clause}
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            params,
        ).fetchone()
    return _analysis_task_dict(row) if row is not None else None


def list_analysis_tasks(
    *,
    limit: int = 50,
    status: str | None = None,
    kind: str | None = None,
    owner_id: str | None = None,
) -> list[dict]:
    clauses: list[str] = []
    params: list = []
    if owner_id:
        clauses.append("owner_id=?")
        params.append(owner_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    sql = "SELECT * FROM analysis_tasks"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [_analysis_task_dict(row) for row in rows]


def list_analysis_tasks_page(
    *,
    limit: int = 50,
    status: str | None = None,
    kind: str | None = None,
    cursor: str | None = None,
    owner_id: str | None = None,
) -> dict:
    clauses: list[str] = []
    params: list = []
    if owner_id:
        clauses.append("owner_id=?")
        params.append(owner_id)
    if status:
        clauses.append("status=?")
        params.append(status)
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    count_sql = "SELECT COUNT(*) AS total FROM analysis_tasks"
    if clauses:
        count_sql += " WHERE " + " AND ".join(clauses)
    page_clauses = list(clauses)
    page_params = list(params)
    if cursor:
        cursor_value, cursor_id = _decode_cursor(cursor)
        page_clauses.append("(created_at < ? OR (created_at = ? AND id < ?))")
        page_params.extend([cursor_value, cursor_value, cursor_id])
    sql = "SELECT * FROM analysis_tasks"
    if page_clauses:
        sql += " WHERE " + " AND ".join(page_clauses)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    page_params.append(limit + 1)
    with _lock, _conn() as c:
        total = int(c.execute(count_sql, params).fetchone()["total"])
        rows = c.execute(sql, page_params).fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    return {
        "items": [_analysis_task_dict(row) for row in page_rows],
        "total": total,
        "next_cursor": (
            _encode_cursor(float(page_rows[-1]["created_at"]), str(page_rows[-1]["id"]))
            if has_more and page_rows
            else None
        ),
    }


def update_analysis_task(task_id: str, patch: dict) -> dict | None:
    allowed = {
        "status",
        "result",
        "error",
        "started_at",
        "finished_at",
        "duration_ms",
    }
    sets: list[str] = []
    params: list = []
    for key, value in patch.items():
        if key not in allowed:
            continue
        column = "result_json" if key == "result" else key
        if key == "result":
            value = json.dumps(value, ensure_ascii=False, default=str)
        sets.append(f"{column}=?")
        params.append(value)
    if not sets:
        return get_analysis_task(task_id)
    sets.append("updated_at=?")
    params.extend([_now(), task_id])
    with _lock, _conn() as c:
        cursor = c.execute(
            f"UPDATE analysis_tasks SET {', '.join(sets)} WHERE id=?",
            params,
        )
    return get_analysis_task(task_id) if cursor.rowcount else None


# ---------------------------------------------------------------------------
# 不可变研究报告与章节事件 research_reports/*
# ---------------------------------------------------------------------------
def _research_report_dict(row) -> dict[str, Any]:
    report_id = row["id"]
    return {
        "id": report_id,
        "owner_id": row["owner_id"],
        "research_run_id": row["research_run_id"],
        "task_id": row["task_id"],
        "mode": row["mode"],
        "version": int(row["version"]),
        "status": row["status"],
        "data_cutoff": row["data_cutoff"],
        "model_version": row["model_version"],
        "prompt_version": row["prompt_version"],
        "snapshot": json.loads(row["snapshot_json"]) if row["snapshot_json"] else None,
        "content_hash": row["content_hash"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "sections": list_research_report_sections(report_id),
    }


def create_research_report(
    *, research_run_id: str, mode: str, owner_id: str, task_id: str | None = None
) -> dict:
    now = _now()
    with _lock, _conn() as c:
        latest = c.execute(
            "SELECT COALESCE(MAX(version),0) AS version FROM research_reports WHERE research_run_id=? AND mode=?",
            (research_run_id, mode),
        ).fetchone()
        version = int(latest["version"]) + 1
        report_id = uuid.uuid4().hex
        c.execute(
            """INSERT INTO research_reports
               (id, owner_id, research_run_id, task_id, mode, version, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?, 'queued', ?, ?)""",
            (report_id, owner_id, research_run_id, task_id, mode, version, now, now),
        )
        row = c.execute("SELECT * FROM research_reports WHERE id=?", (report_id,)).fetchone()
    return _research_report_dict(row)


def get_research_report(report_id: str, *, owner_id: str | None = None) -> dict | None:
    with _lock, _conn() as c:
        sql = "SELECT * FROM research_reports WHERE id=?"
        params: list[Any] = [report_id]
        if owner_id:
            sql += " AND owner_id=?"
            params.append(owner_id)
        row = c.execute(sql, params).fetchone()
    return _research_report_dict(row) if row is not None else None


def list_research_report_sections(report_id: str) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM research_report_sections WHERE report_id=? ORDER BY position ASC",
            (report_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "report_id": row["report_id"],
            "section_key": row["section_key"],
            "position": int(row["position"]),
            "status": row["status"],
            "title": row["title"],
            "body": row["body"],
            "evidence_ids": json.loads(row["evidence_ids_json"] or "[]"),
            "error": row["error"],
            "updated_at": float(row["updated_at"]),
        }
        for row in rows
    ]


def create_research_report_section(
    report_id: str, *, section_key: str, position: int, title: str
) -> dict[str, Any]:
    now = _now()
    section_id = uuid.uuid4().hex
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO research_report_sections
               (id, report_id, section_key, position, title, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(report_id, section_key) DO UPDATE SET position=excluded.position, title=excluded.title""",
            (section_id, report_id, section_key, position, title, now),
        )
        row = c.execute(
            "SELECT * FROM research_report_sections WHERE report_id=? AND section_key=?",
            (report_id, section_key),
        ).fetchone()
    return {
        "id": row["id"],
        "report_id": row["report_id"],
        "section_key": row["section_key"],
        "position": int(row["position"]),
        "status": row["status"],
        "title": row["title"],
        "body": row["body"],
        "evidence_ids": json.loads(row["evidence_ids_json"] or "[]"),
        "error": row["error"],
        "updated_at": float(row["updated_at"]),
    }


def update_research_report_section(section_id: str, patch: dict[str, Any]) -> dict | None:
    with _lock, _conn() as c:
        report_row = c.execute(
            """SELECT r.status FROM research_report_sections s
               JOIN research_reports r ON r.id=s.report_id WHERE s.id=?""",
            (section_id,),
        ).fetchone()
    if report_row is None:
        return None
    if report_row["status"] == "completed":
        raise ValueError("已完成研究报告章节不可变")
    mapping = {
        "status": "status",
        "body": "body",
        "evidence_ids": "evidence_ids_json",
        "error": "error",
    }
    sets, params = [], []
    for key, column in mapping.items():
        if key not in patch:
            continue
        value = patch[key]
        if key == "evidence_ids":
            value = json.dumps(value or [], ensure_ascii=False)
        sets.append(f"{column}=?")
        params.append(value)
    if not sets:
        return None
    sets.append("updated_at=?")
    params.extend([_now(), section_id])
    with _lock, _conn() as c:
        cur = c.execute(f"UPDATE research_report_sections SET {', '.join(sets)} WHERE id=?", params)
        row = c.execute(
            "SELECT * FROM research_report_sections WHERE id=?", (section_id,)
        ).fetchone()
    if not cur.rowcount or row is None:
        return None
    return {
        "id": row["id"],
        "report_id": row["report_id"],
        "section_key": row["section_key"],
        "position": int(row["position"]),
        "status": row["status"],
        "title": row["title"],
        "body": row["body"],
        "evidence_ids": json.loads(row["evidence_ids_json"] or "[]"),
        "error": row["error"],
        "updated_at": float(row["updated_at"]),
    }


def append_research_report_event(
    report_id: str, *, event_type: str, payload: dict[str, Any], section_id: str | None = None
) -> dict[str, Any]:
    now = _now()
    with _lock, _conn() as c:
        report_row = c.execute(
            "SELECT research_run_id, task_id FROM research_reports WHERE id=?", (report_id,)
        ).fetchone()
        current = c.execute(
            "SELECT COALESCE(MAX(sequence),0) AS sequence FROM research_report_events WHERE report_id=?",
            (report_id,),
        ).fetchone()
        sequence = int(current["sequence"]) + 1
        event_id = uuid.uuid4().hex
        event = {
            "id": event_id,
            "report_id": report_id,
            "section_id": section_id,
            "task_id": report_row["task_id"] if report_row else None,
            "research_run_id": report_row["research_run_id"] if report_row else None,
            "event_type": event_type,
            "sequence": sequence,
            "event_version": "report-stream-v1",
            "payload": payload,
            "server_time": now,
        }
        c.execute(
            """INSERT INTO research_report_events
               (id, report_id, section_id, event_type, sequence, event_version, payload_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                event_id,
                report_id,
                section_id,
                event_type,
                sequence,
                "report-stream-v1",
                json.dumps(payload, ensure_ascii=False, default=str),
                now,
            ),
        )
    return event


def list_research_report_events(
    report_id: str, *, after_sequence: int = 0, limit: int = 1000
) -> list[dict[str, Any]]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT e.*, r.task_id, r.research_run_id
               FROM research_report_events e JOIN research_reports r ON r.id=e.report_id
               WHERE e.report_id=? AND e.sequence>? ORDER BY e.sequence ASC LIMIT ?""",
            (report_id, max(0, after_sequence), max(1, min(limit, 5000))),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "report_id": row["report_id"],
            "section_id": row["section_id"],
            "task_id": row["task_id"],
            "research_run_id": row["research_run_id"],
            "event_type": row["event_type"],
            "sequence": int(row["sequence"]),
            "event_version": row["event_version"],
            "payload": json.loads(row["payload_json"] or "{}"),
            "server_time": float(row["created_at"]),
        }
        for row in rows
    ]


def update_research_report(report_id: str, patch: dict[str, Any]) -> dict | None:
    existing = get_research_report(report_id)
    if existing is None:
        return None
    if existing.get("status") == "completed" and any(
        key in patch for key in ("snapshot", "content_hash", "data_cutoff")
    ):
        raise ValueError("已完成研究报告快照不可变")
    mapping = {
        "status": "status",
        "data_cutoff": "data_cutoff",
        "model_version": "model_version",
        "prompt_version": "prompt_version",
        "snapshot": "snapshot_json",
        "content_hash": "content_hash",
    }
    sets, params = [], []
    for key, column in mapping.items():
        if key not in patch:
            continue
        value = patch[key]
        if key == "snapshot":
            value = json.dumps(value, ensure_ascii=False, default=str)
        sets.append(f"{column}=?")
        params.append(value)
    if not sets:
        return get_research_report(report_id)
    sets.append("updated_at=?")
    params.extend([_now(), report_id])
    with _lock, _conn() as c:
        cur = c.execute(f"UPDATE research_reports SET {', '.join(sets)} WHERE id=?", params)
    return get_research_report(report_id) if cur.rowcount else None


# ---------------------------------------------------------------------------
# 因子定义与实验账本 factor_definitions / factor_experiments
# ---------------------------------------------------------------------------
def _factor_research_plan_dict(row) -> dict:
    budget = {
        "maximum_round_candidates": 100,
        "maximum_formula_complexity": 30,
        "maximum_duplicate_rate": 0.25,
        "stop_conditions": {},
        **json.loads(row["budget_json"]),
    }
    return {
        "id": row["id"],
        "title": row["title"],
        "target_market": row["target_market"],
        "budget": budget,
        "created_at": float(row["created_at"]),
    }


def create_factor_research_plan(plan_id: str, title: str, target_market: str, budget: dict) -> dict:
    now = _now()
    payload = json.dumps(budget, ensure_ascii=False, sort_keys=True, default=str)
    with _lock, _conn() as c:
        existing = c.execute(
            "SELECT * FROM factor_research_plans WHERE id=?", (plan_id,)
        ).fetchone()
        if existing is not None:
            if (
                existing["title"] != title
                or existing["target_market"] != target_market
                or json.dumps(
                    json.loads(existing["budget_json"]),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                )
                != payload
            ):
                raise ValueError("研究计划已存在且不可修改")
            return _factor_research_plan_dict(existing)
        c.execute(
            """INSERT INTO factor_research_plans
               (id, title, target_market, budget_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (plan_id, title, target_market, payload, now),
        )
        row = c.execute("SELECT * FROM factor_research_plans WHERE id=?", (plan_id,)).fetchone()
    return _factor_research_plan_dict(row)


def get_factor_research_plan(plan_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM factor_research_plans WHERE id=?", (plan_id,)).fetchone()
    return _factor_research_plan_dict(row) if row else None


def list_factor_research_plans(target_market: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        if target_market:
            rows = c.execute(
                """SELECT * FROM factor_research_plans WHERE target_market=?
                   ORDER BY created_at DESC""",
                (target_market,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM factor_research_plans ORDER BY created_at DESC"
            ).fetchall()
    return [_factor_research_plan_dict(row) for row in rows]


def _factor_confirmation_opening_dict(row) -> dict:
    return {
        "id": row["id"],
        "research_plan_id": row["research_plan_id"],
        "experiment_id": row["experiment_id"],
        "confirmation_data_fingerprint": row["confirmation_data_fingerprint"],
        "opened_by": row["opened_by"],
        "irreversible_ack": bool(row["irreversible_ack"]),
        "created_at": float(row["created_at"]),
    }


def get_factor_confirmation_opening(research_plan_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM factor_confirmation_set_openings WHERE research_plan_id=?",
            (research_plan_id,),
        ).fetchone()
    return _factor_confirmation_opening_dict(row) if row else None


def create_factor_confirmation_opening(
    *,
    research_plan_id: str,
    experiment_id: str,
    confirmation_data_fingerprint: str,
    opened_by: str,
    irreversible_ack: bool,
) -> dict:
    now = _now()
    normalized_fingerprint = confirmation_data_fingerprint.lower()
    with _lock, _conn() as c:
        existing = c.execute(
            "SELECT * FROM factor_confirmation_set_openings WHERE research_plan_id=?",
            (research_plan_id,),
        ).fetchone()
        if existing is not None:
            immutable_values = {
                "experiment_id": experiment_id,
                "confirmation_data_fingerprint": normalized_fingerprint,
                "opened_by": opened_by,
                "irreversible_ack": int(irreversible_ack),
            }
            if any(existing[key] != value for key, value in immutable_values.items()):
                raise ValueError("锁定确认集已经开启且审计记录不可修改")
            return _factor_confirmation_opening_dict(existing)
        opening_id = uuid.uuid4().hex
        c.execute(
            """INSERT INTO factor_confirmation_set_openings
               (id, research_plan_id, experiment_id, confirmation_data_fingerprint,
                opened_by, irreversible_ack, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                opening_id,
                research_plan_id,
                experiment_id,
                normalized_fingerprint,
                opened_by,
                int(irreversible_ack),
                now,
            ),
        )
        row = c.execute(
            "SELECT * FROM factor_confirmation_set_openings WHERE id=?", (opening_id,)
        ).fetchone()
    return _factor_confirmation_opening_dict(row)


def _factor_definition_dict(row) -> dict:
    payload = json.loads(row["payload_json"])
    return {
        "id": row["id"],
        **payload,
        "factor_key": row["factor_key"],
        "version": row["version"],
        "formula_hash": row["formula_hash"],
        "definition_hash": row["definition_hash"],
        "family": row["family"],
        "market": row["market"],
        "created_at": float(row["created_at"]),
    }


def _factor_lifecycle_event_dict(row) -> dict:
    return {
        "id": row["id"],
        "factor_definition_id": row["factor_definition_id"],
        "event_sequence": int(row["event_sequence"]),
        "state": row["state"],
        "target_market": row["target_market"],
        "actor_type": row["actor_type"],
        "actor": row["actor"],
        "rule": row["rule"],
        "evidence": json.loads(row["evidence_json"] or "{}"),
        "created_at": float(row["created_at"]),
    }


def _ensure_factor_lifecycle_draft(
    connection: database.ConnectionAdapter,
    definition_row,
    target_market: str,
) -> None:
    existing = connection.execute(
        """SELECT 1 FROM factor_lifecycle_events
           WHERE factor_definition_id=? AND target_market=? LIMIT 1""",
        (definition_row["id"], target_market),
    ).fetchone()
    if existing is not None:
        return
    payload = json.loads(definition_row["payload_json"])
    evidence = {
        "formula_definition_hash": definition_row["definition_hash"],
        "formula_hash": definition_row["formula_hash"],
        "formula_version": definition_row["version"],
        "data_snapshot_hash": "not_applicable",
        "cumulative_attempts": 0,
        "validation_window": {"start": None, "end": None},
        "cost_profile_version": "not_applicable",
        "gate_version": "factor-lifecycle-v1",
        "definition_market": payload.get("market"),
    }
    connection.execute(
        """INSERT INTO factor_lifecycle_events
           (id, factor_definition_id, event_sequence, state, target_market,
            actor_type, actor, rule, evidence_json, created_at)
           VALUES (?, ?, 1, 'draft', ?, 'system', 'factor_registry',
                   'definition_registered', ?, ?)""",
        (
            uuid.uuid4().hex,
            definition_row["id"],
            target_market,
            json.dumps(evidence, ensure_ascii=False, default=str),
            _now(),
        ),
    )


def create_factor_definition(payload: dict[str, Any]) -> dict:
    definition_id = uuid.uuid4().hex
    now = _now()
    factor_key = str(payload["key"])
    version = str(payload["version"])
    formula_hash = str(payload["formula_hash"])
    definition_hash = str(payload["definition_hash"])
    family = str(payload["family"])
    market = str(payload["market"])
    with _lock, _conn() as c:
        existing = c.execute(
            "SELECT * FROM factor_definitions WHERE factor_key=? AND version=?",
            (factor_key, version),
        ).fetchone()
        if existing is not None:
            if existing["definition_hash"] != definition_hash:
                raise ValueError("同一因子 key 与 version 已存在不同定义，必须提升版本")
            initial_market = market if market != "all" else "all"
            _ensure_factor_lifecycle_draft(c, existing, initial_market)
            return _factor_definition_dict(existing)
        duplicate = c.execute(
            """SELECT factor_key FROM factor_definitions
               WHERE formula_hash=? AND family<>? LIMIT 1""",
            (formula_hash, family),
        ).fetchone()
        if duplicate is not None:
            raise ValueError(f"公式与 {duplicate['factor_key']} 完全重复，请声明为同一因子族或别名")
        c.execute(
            """INSERT INTO factor_definitions
               (id, factor_key, version, formula_hash, definition_hash, family, market,
                payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                definition_id,
                factor_key,
                version,
                formula_hash,
                definition_hash,
                family,
                market,
                json.dumps(payload, ensure_ascii=False, default=str),
                now,
            ),
        )
        row = c.execute("SELECT * FROM factor_definitions WHERE id=?", (definition_id,)).fetchone()
        initial_market = market if market != "all" else "all"
        _ensure_factor_lifecycle_draft(c, row, initial_market)
    return _factor_definition_dict(row)


def ensure_factor_lifecycle_draft(
    factor_definition_id: str,
    target_market: str,
) -> dict | None:
    with _lock, _conn() as c:
        definition = c.execute(
            "SELECT * FROM factor_definitions WHERE id=?", (factor_definition_id,)
        ).fetchone()
        if definition is None:
            return None
        _ensure_factor_lifecycle_draft(c, definition, target_market)
        row = c.execute(
            """SELECT * FROM factor_lifecycle_events
               WHERE factor_definition_id=? AND target_market=?
               ORDER BY event_sequence DESC, created_at DESC, id DESC LIMIT 1""",
            (factor_definition_id, target_market),
        ).fetchone()
    return _factor_lifecycle_event_dict(row) if row else None


def list_factor_lifecycle_events(
    factor_definition_id: str,
    *,
    target_market: str | None = None,
) -> list[dict]:
    clauses = ["factor_definition_id=?"]
    params: list[Any] = [factor_definition_id]
    if target_market:
        clauses.append("target_market=?")
        params.append(target_market)
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT * FROM factor_lifecycle_events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY target_market ASC, event_sequence ASC, created_at ASC, id ASC",
            params,
        ).fetchall()
    return [_factor_lifecycle_event_dict(row) for row in rows]


def get_latest_factor_lifecycle_event(
    factor_definition_id: str,
    target_market: str,
) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            """SELECT * FROM factor_lifecycle_events
               WHERE factor_definition_id=? AND target_market=?
               ORDER BY event_sequence DESC, created_at DESC, id DESC LIMIT 1""",
            (factor_definition_id, target_market),
        ).fetchone()
    return _factor_lifecycle_event_dict(row) if row else None


def append_factor_lifecycle_event(
    factor_definition_id: str,
    *,
    expected_state: str,
    state: str,
    target_market: str,
    actor_type: str,
    actor: str,
    rule: str,
    evidence: dict,
) -> dict:
    with _lock, _conn() as c:
        definition = c.execute(
            "SELECT * FROM factor_definitions WHERE id=?", (factor_definition_id,)
        ).fetchone()
        if definition is None:
            raise ValueError("因子定义不存在")
        _ensure_factor_lifecycle_draft(c, definition, target_market)
        latest = c.execute(
            """SELECT * FROM factor_lifecycle_events
               WHERE factor_definition_id=? AND target_market=?
               ORDER BY event_sequence DESC, created_at DESC, id DESC LIMIT 1""",
            (factor_definition_id, target_market),
        ).fetchone()
        if latest is None or latest["state"] != expected_state:
            actual = latest["state"] if latest else "missing"
            raise ValueError(f"因子生命周期已变化：预期 {expected_state}，实际 {actual}")
        sequence = int(latest["event_sequence"]) + 1
        event_id = uuid.uuid4().hex
        c.execute(
            """INSERT INTO factor_lifecycle_events
               (id, factor_definition_id, event_sequence, state, target_market,
                actor_type, actor, rule, evidence_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                factor_definition_id,
                sequence,
                state,
                target_market,
                actor_type,
                actor,
                rule,
                json.dumps(evidence, ensure_ascii=False, default=str),
                _now(),
            ),
        )
        row = c.execute("SELECT * FROM factor_lifecycle_events WHERE id=?", (event_id,)).fetchone()
    return _factor_lifecycle_event_dict(row)


def get_factor_definition(factor_key: str, version: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM factor_definitions WHERE factor_key=? AND version=?",
            (factor_key, version),
        ).fetchone()
    return _factor_definition_dict(row) if row else None


def list_factor_definitions(*, market: str | None = None, family: str | None = None) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if market:
        clauses.append("market IN (?, 'all')")
        params.append(market)
    if family:
        clauses.append("family=?")
        params.append(family)
    sql = "SELECT * FROM factor_definitions"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY factor_key ASC, version DESC"
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [_factor_definition_dict(row) for row in rows]


def _factor_candidate_validation_dict(row) -> dict:
    return {
        "id": row["id"],
        "factor_definition_id": row["factor_definition_id"],
        "data_fingerprint": row["data_fingerprint"],
        "report": json.loads(row["report_json"]),
        "created_at": float(row["created_at"]),
    }


def create_factor_candidate_validation(
    factor_definition_id: str, data_fingerprint: str, report: dict
) -> dict:
    validation_id = uuid.uuid4().hex
    now = _now()
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO factor_candidate_validations
               (id, factor_definition_id, data_fingerprint, report_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                validation_id,
                factor_definition_id,
                data_fingerprint,
                json.dumps(report, ensure_ascii=False, default=str),
                now,
            ),
        )
        row = c.execute(
            "SELECT * FROM factor_candidate_validations WHERE id=?", (validation_id,)
        ).fetchone()
    return _factor_candidate_validation_dict(row)


def get_factor_candidate_validation(validation_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM factor_candidate_validations WHERE id=?", (validation_id,)
        ).fetchone()
    return _factor_candidate_validation_dict(row) if row else None


def list_factor_candidate_validations(factor_definition_id: str, *, limit: int = 100) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT * FROM factor_candidate_validations
               WHERE factor_definition_id=? ORDER BY created_at DESC LIMIT ?""",
            (factor_definition_id, limit),
        ).fetchall()
    return [_factor_candidate_validation_dict(row) for row in rows]


def _factor_experiment_event_dict(row) -> dict:
    return {
        "id": row["id"],
        "experiment_id": row["experiment_id"],
        "event_sequence": int(row["event_sequence"]),
        "status": row["status"],
        "result": json.loads(row["result_json"] or "{}"),
        "failure_reason": row["failure_reason"],
        "failure_code": row["failure_code"],
        "evidence": json.loads(row["evidence_json"] or "{}"),
        "created_at": float(row["created_at"]),
    }


def _factor_experiment_dict(row) -> dict:
    model = json.loads(row["model_json"] or "{}")
    prompt = json.loads(row["prompt_json"] or "{}")
    proposal = json.loads(row["proposal_json"] or "{}")
    pre_registration = json.loads(row["pre_registration_json"])
    result = json.loads(row["latest_result_json"] or "{}")

    def content_hash(value: Any) -> str:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return {
        "id": row["id"],
        "research_plan_id": row["research_plan_id"],
        "hypothesis": row["hypothesis"],
        "source": row["source"],
        "parent_experiment_id": row["parent_experiment_id"],
        "factor_definition_id": row["factor_definition_id"],
        "candidate_validation_id": row["candidate_validation_id"],
        "factor_key": row["factor_key"],
        "factor_version": row["factor_version"],
        "factor_family": row["factor_family"],
        "target_market": row["target_market"],
        "data_start": row["data_start"],
        "data_end": row["data_end"],
        "parameter_grid": json.loads(row["parameter_grid_json"] or "{}"),
        "parameter_combinations": int(row["parameter_combinations"]),
        "estimated_compute_units": int(row["estimated_compute_units"]),
        "model": model,
        "prompt": prompt,
        "ai_trace": proposal.get("ai_trace", {}),
        "proposal": proposal,
        "pre_registration": pre_registration,
        "attempt_number": int(row["attempt_number"]),
        "status": row["current_status"],
        "created_at": float(row["created_at"]),
        "provenance": {
            "schema_version": "factor-experiment-provenance-v1",
            "formula": {
                "version": row["factor_version"],
                "formula_hash": row["definition_formula_hash"],
                "definition_hash": row["definition_hash"],
            },
            "data": {
                "version": "candidate-validation-v1",
                "snapshot_hash": row["validation_data_fingerprint"],
            },
            "experiment": {
                "version": "factor-experiment-ledger-v1",
                "hash": content_hash(
                    {
                        "hypothesis": row["hypothesis"],
                        "source": row["source"],
                        "parameter_grid": json.loads(row["parameter_grid_json"] or "{}"),
                        "pre_registration": pre_registration,
                    }
                ),
            },
            "model": {
                "version": str(model.get("version") or model.get("model") or "not_used"),
                "hash": content_hash(model),
            },
            "prompt": {
                "version": str(prompt.get("version", "not_used")),
                "hash": content_hash(prompt),
            },
            "cost": {
                "version": "pre-registration-cost-v1",
                "hash": content_hash(
                    {
                        "estimated_compute_units": int(row["estimated_compute_units"]),
                        "maximum_llm_tokens": pre_registration.get("maximum_llm_tokens", 0),
                    }
                ),
            },
            "result": {
                "version": "factor-experiment-result-v1",
                "hash": content_hash(result),
                "status": row["current_status"],
            },
        },
    }


_FACTOR_EXPERIMENT_SELECT = """SELECT e.*, d.factor_key,
    d.version AS factor_version, d.family AS factor_family,
    d.formula_hash AS definition_formula_hash, d.definition_hash AS definition_hash,
    cv.data_fingerprint AS validation_data_fingerprint,
    (SELECT status FROM factor_experiment_events event
     WHERE event.experiment_id=e.id
     ORDER BY event.event_sequence DESC, event.created_at DESC, event.id DESC LIMIT 1)
     AS current_status,
    (SELECT event.result_json FROM factor_experiment_events event
     WHERE event.experiment_id=e.id
     ORDER BY event.event_sequence DESC, event.created_at DESC, event.id DESC LIMIT 1)
     AS latest_result_json
    FROM factor_experiments e
    JOIN factor_definitions d ON d.id=e.factor_definition_id
    LEFT JOIN factor_candidate_validations cv ON cv.id=e.candidate_validation_id"""


def create_factor_experiment(
    *,
    research_plan_id: str,
    hypothesis: str,
    source: str,
    parent_experiment_id: str | None,
    factor_definition_id: str,
    candidate_validation_id: str,
    target_market: str,
    data_start: str | None,
    data_end: str | None,
    parameter_grid: dict,
    parameter_combinations: int,
    estimated_compute_units: int,
    model: dict,
    prompt: dict,
    proposal: dict,
    pre_registration: dict,
) -> dict:
    experiment_id = uuid.uuid4().hex
    event_id = uuid.uuid4().hex
    now = _now()
    with _lock, _conn() as c:
        if parent_experiment_id:
            parent = c.execute(
                "SELECT 1 FROM factor_experiments WHERE id=?", (parent_experiment_id,)
            ).fetchone()
            if parent is None:
                raise ValueError("父实验不存在")
        attempt_row = c.execute(
            """SELECT COUNT(*) AS attempts FROM factor_experiments
               WHERE research_plan_id=?""",
            (research_plan_id,),
        ).fetchone()
        attempt_number = int(attempt_row["attempts"]) + 1
        c.execute(
            """INSERT INTO factor_experiments
               (id, research_plan_id, hypothesis, source, parent_experiment_id,
                factor_definition_id, candidate_validation_id, target_market, data_start, data_end,
                parameter_grid_json, parameter_combinations, estimated_compute_units,
                model_json, prompt_json,
                proposal_json, pre_registration_json, attempt_number, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                experiment_id,
                research_plan_id,
                hypothesis,
                source,
                parent_experiment_id,
                factor_definition_id,
                candidate_validation_id,
                target_market,
                data_start,
                data_end,
                json.dumps(parameter_grid, ensure_ascii=False, default=str),
                parameter_combinations,
                estimated_compute_units,
                json.dumps(model, ensure_ascii=False, default=str),
                json.dumps(prompt, ensure_ascii=False, default=str),
                json.dumps(proposal, ensure_ascii=False, default=str),
                json.dumps(pre_registration, ensure_ascii=False, default=str),
                attempt_number,
                now,
            ),
        )
        c.execute(
            """INSERT INTO factor_experiment_events
               (id, experiment_id, event_sequence, status, result_json, failure_reason,
                failure_code, evidence_json, created_at)
               VALUES (?, ?, 1, 'draft', '{}', NULL, NULL, '{}', ?)""",
            (event_id, experiment_id, now),
        )
    result = get_factor_experiment(experiment_id)
    if result is None:
        raise RuntimeError("因子实验创建后无法读取")
    return result


def add_factor_experiment_event(
    experiment_id: str,
    *,
    status: str,
    result: dict,
    failure_reason: str | None,
    failure_code: str | None,
    evidence: dict,
) -> dict | None:
    event_id = uuid.uuid4().hex
    now = _now()
    with _lock, _conn() as c:
        exists = c.execute(
            "SELECT 1 FROM factor_experiments WHERE id=?", (experiment_id,)
        ).fetchone()
        if exists is None:
            return None
        sequence_row = c.execute(
            """SELECT COALESCE(MAX(event_sequence), 0) AS event_sequence
               FROM factor_experiment_events WHERE experiment_id=?""",
            (experiment_id,),
        ).fetchone()
        event_sequence = int(sequence_row["event_sequence"]) + 1
        c.execute(
            """INSERT INTO factor_experiment_events
               (id, experiment_id, event_sequence, status, result_json, failure_reason,
                failure_code, evidence_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                experiment_id,
                event_sequence,
                status,
                json.dumps(result, ensure_ascii=False, default=str),
                failure_reason,
                failure_code,
                json.dumps(evidence, ensure_ascii=False, default=str),
                now,
            ),
        )
        row = c.execute("SELECT * FROM factor_experiment_events WHERE id=?", (event_id,)).fetchone()
    return _factor_experiment_event_dict(row)


def list_factor_experiment_events(experiment_id: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT * FROM factor_experiment_events WHERE experiment_id=?
               ORDER BY event_sequence ASC, created_at ASC, id ASC""",
            (experiment_id,),
        ).fetchall()
    return [_factor_experiment_event_dict(row) for row in rows]


def _factor_ai_search_round_dict(row) -> dict:
    candidate_count = int(row["candidate_count"])
    duplicate_count = int(row["duplicate_count"])
    status = row["status"]
    return {
        "id": row["id"],
        "research_plan_id": row["research_plan_id"],
        "round_id": row["round_id"],
        "candidate_count": candidate_count,
        "duplicate_count": duplicate_count,
        "duplicate_rate": duplicate_count / candidate_count if candidate_count else 0.0,
        "max_formula_complexity": int(row["max_formula_complexity"]),
        "llm_tokens": int(row["llm_tokens"]),
        "input_fingerprint": row["input_fingerprint"],
        "approval": json.loads(row["approval_json"] or "{}"),
        "status": status,
        "allowed": status == "allowed",
        "stopped": status == "stopped",
        "stop_reason": row["stop_reason"],
        "created_at": float(row["created_at"]),
    }


def get_factor_ai_search_round(research_plan_id: str, round_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            """SELECT * FROM factor_ai_search_rounds
               WHERE research_plan_id=? AND round_id=?""",
            (research_plan_id, round_id),
        ).fetchone()
    return _factor_ai_search_round_dict(row) if row else None


def create_factor_ai_search_round(
    *,
    research_plan_id: str,
    round_id: str,
    candidate_count: int,
    duplicate_count: int,
    max_formula_complexity: int,
    llm_tokens: int,
    input_fingerprint: str,
    approval: dict,
    status: str,
    stop_reason: str | None,
) -> dict:
    now = _now()
    approval_json = json.dumps(approval, ensure_ascii=False, sort_keys=True)
    with _lock, _conn() as c:
        existing = c.execute(
            """SELECT * FROM factor_ai_search_rounds
               WHERE research_plan_id=? AND round_id=?""",
            (research_plan_id, round_id),
        ).fetchone()
        if existing is not None:
            immutable_values = {
                "candidate_count": candidate_count,
                "duplicate_count": duplicate_count,
                "max_formula_complexity": max_formula_complexity,
                "llm_tokens": llm_tokens,
                "input_fingerprint": input_fingerprint,
                "approval_json": approval_json,
                "status": status,
                "stop_reason": stop_reason,
            }
            if any(existing[key] != value for key, value in immutable_values.items()):
                raise ValueError("AI 搜索轮次已存在且不可修改")
            return _factor_ai_search_round_dict(existing)
        round_record_id = uuid.uuid4().hex
        c.execute(
            """INSERT INTO factor_ai_search_rounds
               (id, research_plan_id, round_id, candidate_count, duplicate_count,
                max_formula_complexity, llm_tokens, input_fingerprint, approval_json,
                status, stop_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                round_record_id,
                research_plan_id,
                round_id,
                candidate_count,
                duplicate_count,
                max_formula_complexity,
                llm_tokens,
                input_fingerprint,
                approval_json,
                status,
                stop_reason,
                now,
            ),
        )
        row = c.execute(
            "SELECT * FROM factor_ai_search_rounds WHERE id=?", (round_record_id,)
        ).fetchone()
    return _factor_ai_search_round_dict(row)


def list_factor_ai_search_rounds(research_plan_id: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT * FROM factor_ai_search_rounds WHERE research_plan_id=?
               ORDER BY created_at ASC, id ASC""",
            (research_plan_id,),
        ).fetchall()
    return [_factor_ai_search_round_dict(row) for row in rows]


def get_factor_experiment(experiment_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(_FACTOR_EXPERIMENT_SELECT + " WHERE e.id=?", (experiment_id,)).fetchone()
    if row is None:
        return None
    result = _factor_experiment_dict(row)
    result["events"] = list_factor_experiment_events(experiment_id)
    return result


def list_factor_experiments(
    *,
    research_plan_id: str | None = None,
    source: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if research_plan_id:
        clauses.append("e.research_plan_id=?")
        params.append(research_plan_id)
    if source:
        clauses.append("e.source=?")
        params.append(source)
    sql = _FACTOR_EXPERIMENT_SELECT
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY e.created_at DESC, e.id DESC"
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    items = [_factor_experiment_dict(row) for row in rows]
    if status:
        items = [item for item in items if item["status"] == status]
    return items[:limit]


# ---------------------------------------------------------------------------
# 因子股票池 factor_universes / factor_universe_members
# ---------------------------------------------------------------------------
def _factor_universe_dict(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "market": row["market"],
        "description": row["description"],
        "current_version_id": row["current_version_id"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def _factor_universe_member_dict(row) -> dict:
    return {
        "id": row["id"],
        "universe_id": row["universe_id"],
        "instrument_id": row["instrument_id"],
        "symbol": row["symbol"],
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "status": row["status"],
        "industry": row["industry"],
        "market_cap": row["market_cap"],
        "beta": row["beta"],
        "is_st": bool(row["is_st"]),
        "listed_at": row["listed_at"],
        "delisted_at": row["delisted_at"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def create_factor_universe(name: str, market: str, description: str) -> dict:
    universe_id = uuid.uuid4().hex
    now = _now()
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO factor_universes
               (id, name, market, description, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (universe_id, name, market, description, now, now),
        )
        row = c.execute("SELECT * FROM factor_universes WHERE id=?", (universe_id,)).fetchone()
    return _factor_universe_dict(row)


def get_factor_universe(universe_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM factor_universes WHERE id=?", (universe_id,)).fetchone()
    return _factor_universe_dict(row) if row else None


def list_factor_universes(market: str | None = None) -> list[dict]:
    with _lock, _conn() as c:
        if market:
            rows = c.execute(
                "SELECT * FROM factor_universes WHERE market=? ORDER BY updated_at DESC",
                (market,),
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM factor_universes ORDER BY updated_at DESC").fetchall()
    return [_factor_universe_dict(row) for row in rows]


def upsert_factor_universe_member(
    *,
    universe_id: str,
    instrument_id: str,
    symbol: str,
    effective_from: str,
    effective_to: str | None,
    status: str,
    industry: str,
    market_cap: float | None,
    beta: float | None,
    is_st: bool,
    listed_at: str | None,
    delisted_at: str | None,
) -> dict:
    now = _now()
    with _lock, _conn() as c:
        existing = c.execute(
            """SELECT id FROM factor_universe_members
               WHERE universe_id=? AND symbol=? AND effective_from=?""",
            (universe_id, symbol, effective_from),
        ).fetchone()
        member_id = existing["id"] if existing else uuid.uuid4().hex
        overlap = c.execute(
            """SELECT id FROM factor_universe_members
               WHERE universe_id=? AND symbol=? AND id<>?
                 AND effective_from<=?
                 AND (effective_to IS NULL OR effective_to>=?)
               LIMIT 1""",
            (
                universe_id,
                symbol,
                member_id,
                effective_to or "9999-12-31",
                effective_from,
            ),
        ).fetchone()
        if overlap:
            raise ValueError("成分生效区间与已有记录重叠")
        if existing:
            c.execute(
                """UPDATE factor_universe_members SET instrument_id=?, effective_to=?,
                   status=?, industry=?, market_cap=?, beta=?, is_st=?, listed_at=?,
                   delisted_at=?, updated_at=? WHERE id=?""",
                (
                    instrument_id,
                    effective_to,
                    status,
                    industry,
                    market_cap,
                    beta,
                    1 if is_st else 0,
                    listed_at,
                    delisted_at,
                    now,
                    member_id,
                ),
            )
        else:
            c.execute(
                """INSERT INTO factor_universe_members
                   (id, universe_id, instrument_id, symbol, effective_from, effective_to,
                    status, industry, market_cap, beta, is_st, listed_at, delisted_at,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    member_id,
                    universe_id,
                    instrument_id,
                    symbol,
                    effective_from,
                    effective_to,
                    status,
                    industry,
                    market_cap,
                    beta,
                    1 if is_st else 0,
                    listed_at,
                    delisted_at,
                    now,
                    now,
                ),
            )
        c.execute("UPDATE factor_universes SET updated_at=? WHERE id=?", (now, universe_id))
        row = c.execute("SELECT * FROM factor_universe_members WHERE id=?", (member_id,)).fetchone()
    return _factor_universe_member_dict(row)


def list_factor_universe_members(
    universe_id: str,
    *,
    active_on: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    with _lock, _conn() as c:
        universe = c.execute(
            "SELECT current_version_id FROM factor_universes WHERE id=?", (universe_id,)
        ).fetchone()
        if universe and universe["current_version_id"]:
            version = c.execute(
                "SELECT members_json FROM factor_universe_versions WHERE id=?",
                (universe["current_version_id"],),
            ).fetchone()
            if version is not None:
                members = json.loads(version["members_json"] or "[]")
                if active_on:
                    return [
                        item
                        for item in members
                        if item["effective_from"] <= active_on
                        and (item.get("effective_to") is None or item["effective_to"] >= active_on)
                    ]
                if start_date or end_date:
                    return [
                        item
                        for item in members
                        if (
                            not start_date
                            or item.get("effective_to") is None
                            or item["effective_to"] >= start_date
                        )
                        and (not end_date or item["effective_from"] <= end_date)
                    ]
                return members
    clauses = ["universe_id=?"]
    params: list[Any] = [universe_id]
    if active_on:
        clauses.extend(["effective_from<=?", "(effective_to IS NULL OR effective_to>=?)"])
        params.extend([active_on, active_on])
    else:
        if start_date:
            clauses.append("(effective_to IS NULL OR effective_to>=?)")
            params.append(start_date)
        if end_date:
            clauses.append("effective_from<=?")
            params.append(end_date)
    with _lock, _conn() as c:
        rows = c.execute(
            f"""SELECT * FROM factor_universe_members
                WHERE {" AND ".join(clauses)}
                ORDER BY symbol, effective_from""",
            params,
        ).fetchall()
    return [_factor_universe_member_dict(row) for row in rows]


def create_factor_universe_version(
    universe_id: str,
    *,
    members: list[dict[str, Any]],
    source: str,
    parent_version_id: str | None = None,
) -> dict:
    canonical = json.dumps(members, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    version_id = f"UV-{uuid.uuid4().hex[:16].upper()}"
    now = _now()
    with _lock, _conn() as c:
        latest = c.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM factor_universe_versions WHERE universe_id=?",
            (universe_id,),
        ).fetchone()
        version = int(latest["version"]) + 1
        c.execute(
            """INSERT INTO factor_universe_versions
               (id, universe_id, version, parent_version_id, source, snapshot_hash,
                members_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                version_id,
                universe_id,
                version,
                parent_version_id,
                source,
                snapshot_hash,
                canonical,
                now,
            ),
        )
        c.execute(
            "UPDATE factor_universes SET current_version_id=?, updated_at=? WHERE id=?",
            (version_id, now, universe_id),
        )
    return {
        "id": version_id,
        "universe_id": universe_id,
        "version": version,
        "parent_version_id": parent_version_id,
        "source": source,
        "snapshot_hash": snapshot_hash,
        "members": members,
        "created_at": now,
    }


def get_factor_universe_version(version_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM factor_universe_versions WHERE id=?", (version_id,)
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "universe_id": row["universe_id"],
        "version": int(row["version"]),
        "parent_version_id": row["parent_version_id"],
        "source": row["source"],
        "snapshot_hash": row["snapshot_hash"],
        "members": json.loads(row["members_json"] or "[]"),
        "created_at": float(row["created_at"]),
    }


def list_factor_universe_versions(universe_id: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT id FROM factor_universe_versions WHERE universe_id=?
               ORDER BY version DESC""",
            (universe_id,),
        ).fetchall()
    return [item for row in rows if (item := get_factor_universe_version(row["id"])) is not None]


def set_factor_universe_current_version(universe_id: str, version_id: str) -> None:
    now = _now()
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT universe_id FROM factor_universe_versions WHERE id=?", (version_id,)
        ).fetchone()
        if row is None or row["universe_id"] != universe_id:
            raise KeyError(version_id)
        c.execute(
            "UPDATE factor_universes SET current_version_id=?, updated_at=? WHERE id=?",
            (version_id, now, universe_id),
        )


def get_factor_universe_batch(universe_id: str, idempotency_key: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute(
            """SELECT * FROM factor_universe_batches
               WHERE universe_id=? AND idempotency_key=?""",
            (universe_id, idempotency_key),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "universe_id": row["universe_id"],
        "idempotency_key": row["idempotency_key"],
        "source": row["source"],
        "status": row["status"],
        "diff": json.loads(row["diff_json"] or "{}"),
        "errors": json.loads(row["errors_json"] or "[]"),
        "version_id": row["version_id"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def save_factor_universe_batch(
    universe_id: str,
    *,
    idempotency_key: str,
    source: str,
    status: str,
    diff: dict[str, Any],
    errors: list[dict[str, Any]],
    version_id: str | None,
) -> dict:
    now = _now()
    existing = get_factor_universe_batch(universe_id, idempotency_key)
    if existing and existing["status"] == "succeeded":
        return existing
    batch_id = existing["id"] if existing else f"UB-{uuid.uuid4().hex[:16].upper()}"
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO factor_universe_batches
               (id, universe_id, idempotency_key, source, status, diff_json,
                errors_json, version_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(universe_id, idempotency_key) DO UPDATE SET
                   status=excluded.status, diff_json=excluded.diff_json,
                   errors_json=excluded.errors_json, version_id=excluded.version_id,
                   updated_at=excluded.updated_at""",
            (
                batch_id,
                universe_id,
                idempotency_key,
                source,
                status,
                json.dumps(diff, ensure_ascii=False, default=str),
                json.dumps(errors, ensure_ascii=False, default=str),
                version_id,
                now,
                now,
            ),
        )
    result = get_factor_universe_batch(universe_id, idempotency_key)
    if result is None:
        raise RuntimeError("股票池批次保存后无法读取")
    return result


# ---------------------------------------------------------------------------
# 自动因子工厂运行、候选与模拟观察
# ---------------------------------------------------------------------------
def _factor_factory_run_dict(row) -> dict:
    return {
        "id": row["id"],
        "research_plan_id": row["research_plan_id"],
        "status": row["status"],
        "config": json.loads(row["config_json"] or "{}"),
        "result": json.loads(row["result_json"] or "{}"),
        "selected_factor_key": row["selected_factor_key"],
        "selected_factor_version": row["selected_factor_version"],
        "selected_experiment_id": row["selected_experiment_id"],
        "error": row["error"],
        "started_at": float(row["started_at"]),
        "updated_at": float(row["updated_at"]),
        "observation_started_at": (
            float(row["observation_started_at"])
            if row["observation_started_at"] is not None
            else None
        ),
        "observation_ends_at": (
            float(row["observation_ends_at"]) if row["observation_ends_at"] is not None else None
        ),
    }


def create_factor_factory_run(
    run_id: str,
    *,
    research_plan_id: str,
    status: str,
    config: dict,
) -> dict:
    now = _now()
    with _lock, _conn() as c:
        c.execute(
            """INSERT INTO factor_factory_runs
               (id, research_plan_id, status, config_json, result_json,
                started_at, updated_at)
               VALUES (?, ?, ?, ?, '{}', ?, ?)""",
            (
                run_id,
                research_plan_id,
                status,
                json.dumps(config, ensure_ascii=False, default=str),
                now,
                now,
            ),
        )
        row = c.execute("SELECT * FROM factor_factory_runs WHERE id=?", (run_id,)).fetchone()
    return _factor_factory_run_dict(row)


def update_factor_factory_run(
    run_id: str,
    *,
    status: str | None = None,
    result: dict | None = None,
    selected_factor_key: str | None = None,
    selected_factor_version: str | None = None,
    selected_experiment_id: str | None = None,
    error: str | None = None,
    observation_started_at: float | None = None,
    observation_ends_at: float | None = None,
) -> dict | None:
    assignments = ["updated_at=?"]
    params: list[Any] = [_now()]
    values = {
        "status": status,
        "result_json": (
            json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
        ),
        "selected_factor_key": selected_factor_key,
        "selected_factor_version": selected_factor_version,
        "selected_experiment_id": selected_experiment_id,
        "error": error,
        "observation_started_at": observation_started_at,
        "observation_ends_at": observation_ends_at,
    }
    for column, value in values.items():
        if value is not None:
            assignments.append(f"{column}=?")
            params.append(value)
    params.append(run_id)
    with _lock, _conn() as c:
        c.execute(
            f"UPDATE factor_factory_runs SET {', '.join(assignments)} WHERE id=?",
            params,
        )
        row = c.execute("SELECT * FROM factor_factory_runs WHERE id=?", (run_id,)).fetchone()
    return _factor_factory_run_dict(row) if row else None


def get_factor_factory_run(run_id: str) -> dict | None:
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM factor_factory_runs WHERE id=?", (run_id,)).fetchone()
    return _factor_factory_run_dict(row) if row else None


def list_factor_factory_runs(*, status: str | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM factor_factory_runs"
    params: list[Any] = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY started_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with _lock, _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return [_factor_factory_run_dict(row) for row in rows]


def _factor_factory_candidate_dict(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "factor_key": row["factor_key"],
        "factor_version": row["factor_version"],
        "source": row["source"],
        "experiment_id": row["experiment_id"],
        "status": row["status"],
        "rank": int(row["rank_order"]) if row["rank_order"] is not None else None,
        "metrics": json.loads(row["metrics_json"] or "{}"),
        "gate": json.loads(row["gate_json"] or "{}"),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def upsert_factor_factory_candidate(
    *,
    run_id: str,
    factor_key: str,
    factor_version: str,
    source: str,
    status: str,
    experiment_id: str | None = None,
    rank: int | None = None,
    metrics: dict | None = None,
    gate: dict | None = None,
) -> dict:
    now = _now()
    candidate_id = uuid.uuid4().hex
    metrics_json = json.dumps(metrics or {}, ensure_ascii=False, default=str)
    gate_json = json.dumps(gate or {}, ensure_ascii=False, default=str)
    with _lock, _conn() as c:
        existing = c.execute(
            """SELECT id FROM factor_factory_candidates
               WHERE run_id=? AND factor_key=? AND factor_version=?""",
            (run_id, factor_key, factor_version),
        ).fetchone()
        if existing:
            candidate_id = existing["id"]
            c.execute(
                """UPDATE factor_factory_candidates
                   SET source=?, experiment_id=?, status=?, rank_order=?, metrics_json=?,
                       gate_json=?, updated_at=? WHERE id=?""",
                (
                    source,
                    experiment_id,
                    status,
                    rank,
                    metrics_json,
                    gate_json,
                    now,
                    candidate_id,
                ),
            )
        else:
            c.execute(
                """INSERT INTO factor_factory_candidates
                   (id, run_id, factor_key, factor_version, source, experiment_id,
                    status, rank_order, metrics_json, gate_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate_id,
                    run_id,
                    factor_key,
                    factor_version,
                    source,
                    experiment_id,
                    status,
                    rank,
                    metrics_json,
                    gate_json,
                    now,
                    now,
                ),
            )
        row = c.execute(
            "SELECT * FROM factor_factory_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
    return _factor_factory_candidate_dict(row)


def list_factor_factory_candidates(run_id: str) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT * FROM factor_factory_candidates WHERE run_id=?
               ORDER BY CASE WHEN rank_order IS NULL THEN 1 ELSE 0 END,
                        rank_order ASC, created_at ASC""",
            (run_id,),
        ).fetchall()
    return [_factor_factory_candidate_dict(row) for row in rows]


def _factor_factory_observation_dict(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "observed_at": float(row["observed_at"]),
        "market_time": row["market_time"],
        "price": float(row["price"]),
        "signal": float(row["signal"]),
        "position_weight": float(row["position_weight"]),
        "gross_return": float(row["gross_return"]),
        "cost": float(row["cost"]),
        "net_return": float(row["net_return"]),
        "equity": float(row["equity"]),
        "drawdown": float(row["drawdown"]),
        "fill_rate": float(row["fill_rate"]),
        "payload": json.loads(row["payload_json"] or "{}"),
    }


def append_factor_factory_observation(
    run_id: str,
    *,
    market_time: str,
    price: float,
    signal: float,
    position_weight: float,
    gross_return: float,
    cost: float,
    net_return: float,
    equity: float,
    drawdown: float,
    fill_rate: float,
    payload: dict,
) -> tuple[dict, bool]:
    observation_id = uuid.uuid4().hex
    now = _now()
    with _lock, _conn() as c:
        existing = c.execute(
            "SELECT * FROM factor_factory_observations WHERE run_id=? AND market_time=?",
            (run_id, market_time),
        ).fetchone()
        if existing:
            return _factor_factory_observation_dict(existing), False
        c.execute(
            """INSERT INTO factor_factory_observations
               (id, run_id, observed_at, market_time, price, signal, position_weight,
                gross_return, cost, net_return, equity, drawdown, fill_rate, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation_id,
                run_id,
                now,
                market_time,
                price,
                signal,
                position_weight,
                gross_return,
                cost,
                net_return,
                equity,
                drawdown,
                fill_rate,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        row = c.execute(
            "SELECT * FROM factor_factory_observations WHERE id=?", (observation_id,)
        ).fetchone()
    return _factor_factory_observation_dict(row), True


def list_factor_factory_observations(run_id: str, *, limit: int = 10_000) -> list[dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            """SELECT * FROM factor_factory_observations WHERE run_id=?
               ORDER BY observed_at ASC, id ASC LIMIT ?""",
            (run_id, limit),
        ).fetchall()
    return [_factor_factory_observation_dict(row) for row in rows]
