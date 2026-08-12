from __future__ import annotations

import importlib.util
import re
from time import perf_counter

import requests

from apps.api import database, store
from apps.api.domains.backups import service as backup_service
from core.config import get_config, get_path
from core.llm import reset_clients
from packages.credential_vault import (
    OkxCredentials,
    load_okx_demo_credentials,
    okx_demo_credential_status,
    save_okx_demo_credentials,
    update_okx_demo_validation,
)
from packages.credential_vault import (
    delete_okx_demo_credentials as delete_okx_demo_vault,
)

from . import repository
from .domain import mask_secret, provider_key_env

_NOTIFICATION_ENV_FIELDS = {
    "wecom": {
        "webhook_url": "WECOM_WEBHOOK_URL",
        "mentioned_mobile": "WECOM_MENTIONED_MOBILE",
    },
    "webhook": {"url": "ALERT_WEBHOOK_URL"},
    "telegram": {"bot_token": "TG_BOT_TOKEN", "chat_id": "TG_CHAT_ID"},
}

_LLM_PROVIDER_PRESETS = {
    "deepseek": {
        "label": "DeepSeek",
        "description": "DeepSeek 官方 OpenAI 兼容接口",
        "official_url": "https://platform.deepseek.com",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "label": "OpenAI",
        "description": "OpenAI 官方 API",
        "official_url": "https://platform.openai.com",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_env": "OPENAI_API_KEY",
    },
    "custom": {
        "label": "兼容 API",
        "description": "自托管或第三方 OpenAI Response 兼容接口",
        "official_url": "",
        "base_url": "http://localhost:1234/v1",
        "model": "local-model",
        "key_env": "QUANTHUB_CUSTOM_LLM_API_KEY",
    },
}


def okx_demo_status() -> dict:
    return okx_demo_credential_status()


def update_okx_demo_credentials(api_key: str, secret_key: str, passphrase: str) -> dict:
    return save_okx_demo_credentials(OkxCredentials(api_key, secret_key, passphrase))


def delete_okx_demo_credentials() -> dict:
    return delete_okx_demo_vault()


def _okx_error(exc: Exception, stage: str) -> tuple[str, str]:
    if stage == "vault_load":
        return "credential_vault_unavailable", "本机 OKX 凭据无法解密，请删除后重新保存"
    if stage in {"sdk_import", "sdk_initialize", "sandbox_enable"}:
        return "connector_unavailable", "OKX 连接器初始化失败，请检查本机运行环境"
    if _okx_numeric_code(exc) == "50101":
        return "environment_mismatch", "这把 API Key 不属于 OKX Demo，请在模拟交易环境重新创建"
    name = type(exc).__name__
    if name in {"AuthenticationError", "PermissionDenied"}:
        return "authentication_failed", "OKX 拒绝了凭据，请检查 API Key、Secret 和 Passphrase"
    if name in {"NetworkError", "RequestTimeout", "ExchangeNotAvailable", "DDoSProtection"}:
        return "network_unavailable", "无法连接 OKX Demo，请检查网络后重试"
    return "connection_failed", "OKX Demo 只读连接测试失败"


def _okx_numeric_code(exc: Exception) -> str | None:
    match = re.search(r'["\']code["\']\s*:\s*["\']?(\d{4,8})', str(exc))
    return match.group(1) if match else None


def test_okx_demo_connection() -> dict:
    status = okx_demo_credential_status()
    if not status["configured"]:
        return {
            **status,
            "ok": False,
            "error_code": "not_configured",
            "error": "尚未保存 OKX Demo 凭据",
        }
    started = perf_counter()
    stage = "vault_load"
    try:
        credentials = load_okx_demo_credentials()
        stage = "sdk_import"
        import ccxt

        stage = "sdk_initialize"
        exchange = ccxt.okx(
            {
                "apiKey": credentials.api_key,
                "secret": credentials.secret_key,
                "password": credentials.passphrase,
                "enableRateLimit": True,
            }
        )
        exchange.session.trust_env = True
        stage = "sandbox_enable"
        exchange.set_sandbox_mode(True)
        stage = "account_read"
        balance = exchange.fetch_balance()
        totals = balance.get("total") or {}
        nonzero_currencies = sum(1 for value in totals.values() if float(value or 0) != 0)
        update_okx_demo_validation()
        return {
            **okx_demo_credential_status(),
            "ok": True,
            "latency_ms": round((perf_counter() - started) * 1000),
            "currency_count": len(totals),
            "nonzero_currency_count": nonzero_currencies,
            "permission": "read_only_test",
            "error_code": None,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - sanitize every third-party SDK failure
        code, message = _okx_error(exc, stage)
        return {
            **status,
            "ok": False,
            "latency_ms": round((perf_counter() - started) * 1000),
            "currency_count": 0,
            "nonzero_currency_count": 0,
            "permission": "read_only_test",
            "error_code": code,
            "error": message,
            "diagnostic_stage": stage,
            "diagnostic_type": type(exc).__name__,
            "exchange_code": _okx_numeric_code(exc),
        }


def notification_status() -> dict:
    config = get_config()
    alert = config.get("alert", {})
    enabled_channels = set(alert.get("channels", []))
    channels = []
    for channel, fields in _NOTIFICATION_ENV_FIELDS.items():
        values = {
            field: repository.read_runtime_secret(env_name) for field, env_name in fields.items()
        }
        required_fields = (
            ("webhook_url",)
            if channel == "wecom"
            else ("url",)
            if channel == "webhook"
            else ("bot_token", "chat_id")
        )
        channels.append(
            {
                "channel": channel,
                "enabled": channel in enabled_channels,
                "configured": all(bool(values.get(field)) for field in required_fields),
                "fields": {
                    field: mask_secret(value) if value else None for field, value in values.items()
                },
            }
        )
    return {"ok": True, "enabled": bool(alert.get("enabled", False)), "channels": channels}


def update_notification_enabled(enabled: bool) -> dict:
    repository.write_secret("QUANTHUB_ALERT_ENABLED", "1" if enabled else "0")
    repository.set_runtime_secret("QUANTHUB_ALERT_ENABLED", "1" if enabled else "0")
    get_config.cache_clear()
    from core.alert import reset_notifier

    reset_notifier()
    return notification_status()


def update_notification_channel(channel: str, payload: dict) -> dict:
    if channel not in _NOTIFICATION_ENV_FIELDS:
        raise ValueError(f"未知通知通道: {channel}")
    for field, env_name in _NOTIFICATION_ENV_FIELDS[channel].items():
        value = payload.get(field)
        if value is not None:
            repository.write_secret(env_name, value)
            repository.set_runtime_secret(env_name, value)
    current = notification_status()
    channels = {item["channel"] for item in current["channels"] if item["enabled"]}
    if payload["enabled"]:
        channels.add(channel)
    else:
        channels.discard(channel)
    rendered = ",".join(item for item in _NOTIFICATION_ENV_FIELDS if item in channels)
    repository.write_secret("QUANTHUB_ALERT_CHANNELS", rendered)
    repository.set_runtime_secret("QUANTHUB_ALERT_CHANNELS", rendered)
    get_config.cache_clear()
    from core.alert import reset_notifier

    reset_notifier()
    return notification_status()


def test_notification_channel(channel: str) -> dict:
    status = notification_status()
    item = next((row for row in status["channels"] if row["channel"] == channel), None)
    if item is None:
        raise ValueError(f"未知通知通道: {channel}")
    if not item["configured"]:
        raise ValueError(f"通知通道未完整配置: {channel}")
    from core.alert import AlertMessage, Notifier

    sent = Notifier().send_to(
        channel,
        AlertMessage(
            title="QuantHub 通知测试",
            content="这是一条由系统配置页发起的通知测试。",
            level="info",
            source="settings",
        ),
    )
    return {"ok": sent, "channel": channel, "sent": sent}


def credential_status() -> dict:
    config = get_config()
    provider = config.get("llm", {}).get("provider", "deepseek")
    env_name = provider_key_env(config)
    value = repository.read_runtime_secret(env_name)
    provider_config = config.get("llm", {}).get(provider, {})
    preset = _LLM_PROVIDER_PRESETS.get(provider, _LLM_PROVIDER_PRESETS["custom"])
    providers = []
    for provider_id, provider_preset in _LLM_PROVIDER_PRESETS.items():
        provider_env = provider_key_env(config, provider_id)
        saved_config = config.get("llm", {}).get(provider_id, {})
        providers.append(
            {
                "id": provider_id,
                **provider_preset,
                "key_env": provider_env,
                "configured": bool(repository.read_runtime_secret(provider_env)),
                "base_url": str(saved_config.get("base_url") or provider_preset["base_url"]),
                "model": str(saved_config.get("model") or provider_preset["model"]),
                "timeout": int(saved_config.get("timeout", 60)),
                "max_retries": int(saved_config.get("max_retries", 3)),
            }
        )
    base_url = str(provider_config.get("base_url") or preset["base_url"]).rstrip("/")
    return {
        "ok": True,
        "configured": bool(value),
        "provider": provider,
        "provider_label": preset["label"],
        "official_url": preset["official_url"],
        "key_env": env_name,
        "masked": mask_secret(value) if value else None,
        "base_url": base_url,
        "models_endpoint": f"{base_url}/models",
        "model": str(provider_config.get("model") or preset["model"]),
        "timeout": int(provider_config.get("timeout", 60)),
        "max_retries": int(provider_config.get("max_retries", 3)),
        "providers": providers,
    }


def update_credential(api_key: str) -> dict:
    config = get_config()
    env_name = provider_key_env(config)
    repository.write_secret(env_name, api_key)
    repository.set_runtime_secret(env_name, api_key)
    reset_clients()
    get_config.cache_clear()
    return credential_status()


def update_llm_settings(payload: dict) -> dict:
    provider = str(payload["provider"])
    config = get_config()
    env_name = provider_key_env(config, provider)
    api_key = payload.get("api_key")
    if not api_key and not repository.read_runtime_secret(env_name):
        raise ValueError(f"{_LLM_PROVIDER_PRESETS[provider]['label']} 尚未配置 API Key")

    overrides = {
        "QUANTHUB_LLM_PROVIDER": provider,
        "QUANTHUB_LLM_BASE_URL": str(payload["base_url"]),
        "QUANTHUB_LLM_MODEL": str(payload["model"]),
        "QUANTHUB_LLM_TIMEOUT": str(payload["timeout"]),
        "QUANTHUB_LLM_MAX_RETRIES": str(payload["max_retries"]),
        f"QUANTHUB_LLM_{provider.upper()}_BASE_URL": str(payload["base_url"]),
        f"QUANTHUB_LLM_{provider.upper()}_MODEL": str(payload["model"]),
        f"QUANTHUB_LLM_{provider.upper()}_TIMEOUT": str(payload["timeout"]),
        f"QUANTHUB_LLM_{provider.upper()}_MAX_RETRIES": str(payload["max_retries"]),
    }
    for env_key, value in overrides.items():
        repository.write_secret(env_key, value)
        repository.set_runtime_secret(env_key, value)
    if api_key:
        repository.write_secret(env_name, str(api_key))
        repository.set_runtime_secret(env_name, str(api_key))

    get_config.cache_clear()
    reset_clients()
    return credential_status()


def remove_credential() -> dict:
    config = get_config()
    env_name = provider_key_env(config)
    repository.delete_secret(env_name)
    repository.clear_runtime_secret(env_name)
    get_config.cache_clear()
    reset_clients()
    return credential_status()


def test_llm_connection() -> dict:
    status = credential_status()
    if not status["configured"]:
        raise ValueError(f"{status['provider_label']} 尚未配置 API Key")

    started = perf_counter()
    try:
        response = requests.get(
            status["models_endpoint"],
            headers={
                "Authorization": f"Bearer {repository.read_runtime_secret(status['key_env'])}"
            },
            timeout=min(status["timeout"], 30),
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "provider": status["provider"],
            "endpoint": status["models_endpoint"],
            "latency_ms": round((perf_counter() - started) * 1000),
            "status_code": None,
            "models": [],
            "error": f"{type(exc).__name__}: {exc}",
        }

    models: list[str] = []
    if response.ok:
        try:
            payload = response.json()
            models = sorted(
                str(item["id"])
                for item in payload.get("data", [])
                if isinstance(item, dict) and item.get("id")
            )[:100]
        except (TypeError, ValueError):
            pass
    return {
        "ok": response.ok,
        "provider": status["provider"],
        "endpoint": status["models_endpoint"],
        "latency_ms": round((perf_counter() - started) * 1000),
        "status_code": response.status_code,
        "models": models,
        "error": None if response.ok else f"服务返回 HTTP {response.status_code}",
    }


def system_status() -> dict:
    """返回配置页所需的非敏感运行状态。"""
    from apps.api.domains.automation import service as automation_service
    from apps.api.main import PROCESS_STARTED_AT, SOURCE_BUILD_ID, app

    config = get_config()
    alert_status = notification_status()
    llm = credential_status()
    scheduler = automation_service.status()
    a_share_config = get_config("a_shares")
    sentiment_model_dir = a_share_config.get("modules", {}).get("sentiment", {}).get("model_dir")
    sentiment_model_path = (
        get_path("models_dir", "a_shares") / sentiment_model_dir if sentiment_model_dir else None
    )
    optional_modules = {
        name: importlib.util.find_spec(name) is not None
        for name in ("akshare", "snownlp", "torch", "transformers")
    }
    # model_available 原义：FinBERT2 权重目录是否存在。
    # snownlp 自带本地语料模型，安装后即具备本地情绪分析能力，应一并视为「本地模型可用」，
    # 否则会出现「snownlp · 本地模型不可用」的自相矛盾。
    model_available = (
        bool(sentiment_model_path and sentiment_model_path.is_dir()) or optional_modules["snownlp"]
    )
    if optional_modules["transformers"] and optional_modules["torch"] and model_available:
        sentiment_engine = "transformers"
    elif optional_modules["snownlp"]:
        sentiment_engine = "snownlp"
    else:
        sentiment_engine = "keyword"
    if database.is_postgresql(store._DB):
        backups = {
            "supported": False,
            "source_path": "postgresql",
            "source_exists": True,
            "backup_directory": "",
            "backup_count": 0,
            "latest_backup": None,
        }
    else:
        backups = {"supported": True, **backup_service.status()}
    return {
        "ok": True,
        "gateway": {
            "version": app.version,
            "live_trading": bool(config.get("live_trading", False)),
            "store_path": str(backups["source_path"]),
            "deployment_mode": database.deployment_mode(),
            "started_at": PROCESS_STARTED_AT,
            "build_id": SOURCE_BUILD_ID,
        },
        "live_confirm": {
            "enabled": bool(config.get("live_confirm", {}).get("enabled", False)),
            "mode": config.get("live_confirm", {}).get("mode"),
            "timeout_seconds": config.get("live_confirm", {}).get("timeout_seconds"),
        },
        "llm": {
            "provider": llm["provider"],
            "configured": llm["configured"],
            "key_env": llm["key_env"],
        },
        "capabilities": {
            "a_shares": {
                "akshare": optional_modules["akshare"],
            },
            "news_sentiment": {
                "engine": sentiment_engine,
                "snownlp": optional_modules["snownlp"],
                "transformers": optional_modules["transformers"],
                "torch": optional_modules["torch"],
                "model_path": str(sentiment_model_path) if sentiment_model_path else "",
                "model_available": model_available,
            },
        },
        "notifications": {
            "enabled": alert_status["enabled"],
            "channels": alert_status["channels"],
        },
        "scheduler": {
            "ok": scheduler.get("ok", False),
            "total": scheduler.get("total", 0),
            "enabled_count": scheduler.get("enabled_count", 0),
            "running_count": scheduler.get("running_count", 0),
        },
        "backups": {
            "supported": backups["supported"],
            "source_exists": backups["source_exists"],
            "backup_directory": backups["backup_directory"],
            "backup_count": backups["backup_count"],
            "latest_backup": backups["latest_backup"],
        },
    }
