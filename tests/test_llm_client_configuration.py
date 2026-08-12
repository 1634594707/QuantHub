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


if __name__ == "__main__":
    unittest.main()
