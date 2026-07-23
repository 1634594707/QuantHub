"""统一告警通知。

支持企业微信群机器人 / 通用 Webhook / Telegram。
渠道与密钥从 configs/base.yaml: alert 读取（环境变量注入）。

复用原"羊毛监控"的 WeChatPusher 约定，扩展 Webhook / Telegram。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

import requests

from core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class AlertMessage:
    """统一告警消息体。"""

    title: str
    content: str
    level: str = "info"  # info | warning | error
    source: str = "quanthub"  # 模块名
    tags: list[str] | None = None

    def to_text(self) -> str:
        tag_str = " ".join(f"#{t}" for t in (self.tags or []))
        return f"【{self.level.upper()}】【{self.source}】{self.title}\n{self.content}\n{tag_str}".strip()


class Notifier:
    """统一通知器。根据配置分发到启用通道。"""

    def __init__(self) -> None:
        cfg = get_config().get("alert", {})
        self._enabled = cfg.get("enabled", True)
        self._channels: list[str] = list(cfg.get("channels", []))
        self._cfg = cfg

    def _send_wecom(self, msg: AlertMessage) -> bool:
        webhook_url = self._cfg.get("wecom", {}).get("webhook_url")
        if not webhook_url:
            logger.warning("wecom webhook 未配置，跳过")
            return False
        mentioned = self._cfg.get("wecom", {}).get("mentioned_mobile") or ""
        payload = {
            "msgtype": "text",
            "text": {
                "content": msg.to_text(),
                "mentioned_mobile_list": [m.strip() for m in mentioned.split(",") if m.strip()],
            },
        }
        try:
            r = requests.post(webhook_url, json=payload, timeout=10)
            r.raise_for_status()
            return r.json().get("errcode", -1) == 0
        except Exception:
            logger.exception("wecom 通知发送失败")
            return False

    def _send_webhook(self, msg: AlertMessage) -> bool:
        url = self._cfg.get("webhook", {}).get("url")
        if not url:
            logger.warning("webhook url 未配置，跳过")
            return False
        payload = {
            "title": msg.title,
            "content": msg.content,
            "level": msg.level,
            "source": msg.source,
            "tags": msg.tags or [],
        }
        try:
            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()
            return True
        except Exception:
            logger.exception("webhook 通知发送失败")
            return False

    def _send_telegram(self, msg: AlertMessage) -> bool:
        tg = self._cfg.get("telegram", {})
        token, chat_id = tg.get("bot_token"), tg.get("chat_id")
        if not token or not chat_id:
            logger.warning("telegram 配置不全，跳过")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            r = requests.post(url, data={"chat_id": chat_id, "text": msg.to_text()}, timeout=10)
            r.raise_for_status()
            return r.json().get("ok", False)
        except Exception:
            logger.exception("telegram 通知发送失败")
            return False

    def send(self, msg: AlertMessage) -> dict[str, bool]:
        """发送告警到所有启用通道，返回各通道结果。"""
        if not self._enabled or not self._channels:
            logger.info("告警未启用或无通道，丢弃: %s", msg.title)
            return {}
        results: dict[str, bool] = {}
        for ch in self._channels:
            if ch == "wecom":
                results[ch] = self._send_wecom(msg)
            elif ch == "webhook":
                results[ch] = self._send_webhook(msg)
            elif ch == "telegram":
                results[ch] = self._send_telegram(msg)
            else:
                logger.warning("未知告警通道: %s", ch)
        return results

    def send_batch(self, messages: Iterable[AlertMessage]) -> list[dict[str, bool]]:
        return [self.send(m) for m in messages]


# 单例
_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
