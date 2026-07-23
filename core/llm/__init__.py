"""统一 LLM 客户端。

支持 DeepSeek / OpenAI 兼容接口（统一走 openai SDK），支持远程 API。
本地模型（如 FinBERT2）走 transformers 直加载，不经此客户端。

统一管理:
    - API key（仅从环境变量读取）
    - 超时 / 重试
    - token 估算（tiktoken）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import get_config

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """LLM 响应封装。"""

    content: str
    model: str
    usage: dict[str, int] | None = None
    raw: Any = None


class LLMClient:
    """DeepSeek/OpenAI 兼容客户端。"""

    def __init__(self, provider: str | None = None) -> None:
        cfg = get_config().get("llm", {})
        self._provider = provider or cfg.get("provider", "deepseek")
        prov_cfg = cfg.get(self._provider, {})
        self._api_key = prov_cfg.get("api_key")
        self._base_url = prov_cfg.get("base_url")
        self._model = prov_cfg.get("model", "deepseek-chat")
        self._timeout = prov_cfg.get("timeout", 60)
        self._max_retries = prov_cfg.get("max_retries", 3)

        if not self._api_key:
            raise RuntimeError(
                f"LLM provider {self._provider} 的 api_key 未配置"
                f"（环境变量 {prov_cfg.get('api_key_env', '?')}）"
            )

        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("openai 未安装，请运行: pip install openai") from e
        self._OpenAI = OpenAI
        self._client = OpenAI(api_key=self._api_key, base_url=self._base_url, timeout=self._timeout)

    def _retryer(self):
        return retry(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1.5, max=30),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """对话接口。messages 为 OpenAI 格式。"""
        use_model = model or self._model

        @self._retryer()
        def _call():
            params: dict[str, Any] = {
                "model": use_model,
                "messages": messages,
                "temperature": temperature,
                **kwargs,
            }
            if max_tokens is not None:
                params["max_tokens"] = max_tokens
            if response_format is not None:
                params["response_format"] = response_format
            return self._client.chat.completions.create(**params)

        try:
            resp = _call()
        except Exception:
            logger.exception("LLM 调用失败 (%s)", self._provider)
            raise

        choice = resp.choices[0]
        usage = None
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
        return LLMResponse(
            content=choice.message.content or "",
            model=use_model,
            usage=usage,
            raw=resp,
        )

    def estimate_tokens(self, text: str) -> int:
        """粗略估算 token 数（tiktoken，可能不精确适用于中文）。"""
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            # fallback: 字符数 / 2
            return max(1, len(text) // 2)


# 单例缓存（按 provider）
_clients: dict[str, LLMClient] = {}


def get_llm(provider: str | None = None) -> LLMClient:
    """获取 LLM 客户端单例。"""
    key = provider or get_config().get("llm", {}).get("provider", "deepseek")
    if key not in _clients:
        _clients[key] = LLMClient(provider=key)
    return _clients[key]
