import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from core.llm import LLMClient


class LLMClientConfigurationTests(unittest.TestCase):
    def test_provider_timeout_and_retries_reach_openai_transport(self) -> None:
        captured: dict = {}

        class FakeOpenAI:
            def __init__(self, **kwargs) -> None:
                captured.update(kwargs)

        config = {
            "llm": {
                "provider": "deepseek",
                "deepseek": {
                    "api_key": "must-not-leak",
                    "base_url": "https://api.deepseek.test",
                    "model": "deepseek-test",
                    "timeout": 600,
                    "max_retries": 3,
                },
            }
        }
        with (
            patch("core.llm.get_config", return_value=config),
            patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeOpenAI)}),
        ):
            client = LLMClient("deepseek")

        self.assertEqual(client._timeout, 600)
        self.assertEqual(client._max_retries, 3)
        self.assertEqual(captured["timeout"], 600)
        self.assertEqual(captured["max_retries"], 3)

    def test_chat_preserves_provider_finish_reason(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"candidates":[]}'),
                    finish_reason="length",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                prompt_tokens_details=None,
            ),
        )

        class FakeCompletions:
            @staticmethod
            def create(**_kwargs):
                return response

        class FakeOpenAI:
            def __init__(self, **_kwargs) -> None:
                self.chat = SimpleNamespace(completions=FakeCompletions())

        config = {
            "llm": {
                "provider": "deepseek",
                "deepseek": {
                    "api_key": "must-not-leak",
                    "model": "deepseek-test",
                    "max_retries": 1,
                },
            }
        }
        with (
            patch("core.llm.get_config", return_value=config),
            patch.dict(sys.modules, {"openai": SimpleNamespace(OpenAI=FakeOpenAI)}),
        ):
            result = LLMClient("deepseek").chat([{"role": "user", "content": "test"}])

        self.assertEqual(result.finish_reason, "length")


if __name__ == "__main__":
    unittest.main()
