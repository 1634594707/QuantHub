from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.llm import _usage_dict
from strategies.ai_analysis.pa_agent.two_stage import _build_stage2_messages


class PromptCacheTests(unittest.TestCase):
    def test_stage2_keeps_market_context_before_dynamic_diagnosis(self) -> None:
        first = _build_stage2_messages(
            "NVDA",
            "1d",
            "KLINE-CONTEXT",
            {"direction": "bullish", "gate_result": "proceed"},
        )
        second = _build_stage2_messages(
            "NVDA",
            "1d",
            "KLINE-CONTEXT",
            {"direction": "bearish", "gate_result": "proceed"},
        )

        self.assertEqual(first[:2], second[:2])
        self.assertNotEqual(first[2], second[2])
        self.assertIn("KLINE-CONTEXT", first[1]["content"])
        self.assertNotIn("KLINE-CONTEXT", first[3]["content"])

    def test_llm_usage_includes_cached_prompt_tokens(self) -> None:
        usage = SimpleNamespace(
            prompt_tokens=6_898,
            completion_tokens=2_034,
            total_tokens=8_932,
            prompt_tokens_details=SimpleNamespace(cached_tokens=5_888),
        )

        self.assertEqual(
            _usage_dict(usage),
            {
                "prompt_tokens": 6_898,
                "completion_tokens": 2_034,
                "total_tokens": 8_932,
                "cached_prompt_tokens": 5_888,
            },
        )


if __name__ == "__main__":
    unittest.main()
