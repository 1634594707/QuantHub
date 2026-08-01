from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from apps.api.domains.factor_research.ai_review import run_ai_review
from apps.api.domains.factor_research.schemas import FactorAiReviewRequest
from apps.api.domains.factor_research.service import review_factor_research


def research_result() -> dict:
    return {
        "symbol": "AAPL",
        "market": "us_stocks",
        "interval": "1d",
        "source": "test",
        "quality": {"status": "ok", "usable": True, "row_count": 500},
        "summary": {
            "train_rows": 345,
            "purged_rows": 5,
            "test_rows": 150,
            "selected_factors": ["trend_strength"],
        },
        "methodology": {"split": "70/30", "usable_rule": "test IC >= 0.03"},
        "current_signal": {"level": "watch", "drawdown": -0.04},
        "factors": [
            {
                "key": "trend_strength",
                "label": "趋势强度",
                "category": "趋势",
                "status": "usable",
                "selected": True,
                "weight": 1.0,
                "train_ic": 0.12,
                "test_ic": 0.09,
                "icir": 1.1,
                "positive_ic_ratio": 0.6,
                "hit_rate": 0.55,
                "p_value": 0.04,
                "p_value_method": "newey_west_hac",
                "window_pass_rate": 0.6667,
                "passed_windows": 2,
                "window_count": 3,
                "worst_window_ic": -0.01,
                "median_window_ic": 0.09,
                "window_ic_iqr": 0.04,
                "status_transitions": 1,
                "direction_flips": 0,
                "multi_window_consistent": True,
                "windows": [{"fold": 1, "test_ic": 0.08, "status": "pass"}],
                "decay": [{"horizon": 5, "ic": 0.09}],
                "test_observations": 145,
            }
        ],
        "methods": [
            {
                "key": "multifactor",
                "label": "多因子组合",
                "total_return": 0.1,
                "sharpe": 1.0,
                "sortino": 1.2,
                "calmar": 0.8,
                "max_drawdown": -0.12,
                "cvar_95": -0.02,
                "profit_factor": 1.3,
                "trades": 12,
                "exposure": 0.6,
            }
        ],
    }


def valid_review(factor_key: str = "trend_strength") -> dict:
    return {
        "verdict": "谨慎复核",
        "confidence": 78,
        "statistical_alignment": "一致",
        "summary": "样本外方向一致，但仍需跨标的验证。",
        "overfitting_risk": {"level": "中", "reasons": ["单标的样本"]},
        "regime_risk": {"level": "中", "reasons": ["趋势状态依赖"]},
        "factor_reviews": [
            {
                "factor_key": factor_key,
                "assessment": "具备继续研究价值",
                "evidence": ["样本外 IC 0.09"],
                "risks": ["衰减待复核"],
                "regime_fit": ["趋势市场"],
                "next_test": "在滚动窗口和多标的上重复检验",
            }
        ],
        "portfolio_review": {"strengths": ["方向一致"], "risks": ["交易次数有限"]},
        "experiments": [
            {
                "title": "滚动样本外",
                "hypothesis": "因子预测力跨窗口稳定",
                "design": "采用多段 walk-forward",
                "success_criteria": "多数窗口 IC 为正",
            }
        ],
        "uncertainties": ["跨标的泛化能力未知"],
    }


class SequenceClient:
    _provider = "test"

    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return SimpleNamespace(
            content=json.dumps(self.payloads.pop(0), ensure_ascii=False),
            model="test-model",
            usage={"total_tokens": 50},
        )


class FactorAiReviewTests(unittest.TestCase):
    def test_valid_review_preserves_program_status(self) -> None:
        response_client = SequenceClient([valid_review()])
        result = research_result()
        result["summary"]["confirmation_set_labels"] = [0.12, -0.04]
        result["summary"]["hidden_return_rank"] = ["trend_strength"]
        result["factors"][0]["windows"][0]["forward_return_labels"] = [0.08]
        result["methods"][0]["unpublished_profit_rank"] = 1
        response = run_ai_review(result, focus="稳健性", llm=response_client)

        self.assertTrue(response["ok"])
        item = response["review"]["factor_reviews"][0]
        self.assertEqual(item["statistical_status"], "usable")
        self.assertEqual(item["label"], "趋势强度")
        self.assertTrue(response["meta"]["statistical_conclusions_locked"])
        self.assertTrue(response["meta"]["confirmation_labels_excluded"])
        self.assertTrue(response["meta"]["trading_signal_excluded"])
        self.assertFalse(response["meta"]["dynamic_code_execution"])

        _, kwargs = response_client.calls[0]
        self.assertEqual(kwargs["request_timeout"], 120)
        self.assertEqual(kwargs["max_tokens"], 1200)
        self.assertEqual(kwargs["transport_max_retries"], 0)
        encoded_context = json.loads(response_client.calls[0][0][-1]["content"].split("\n", 1)[1])
        reviewed_factor = encoded_context["review_factors"][0]
        self.assertNotIn("current_signal", encoded_context)
        self.assertNotIn("selected_factors", encoded_context["summary"])
        self.assertNotIn("selected", reviewed_factor)
        self.assertFalse(encoded_context["information_boundary"]["locked_sample_data_access"])
        serialized_context = json.dumps(encoded_context, ensure_ascii=False).lower()
        self.assertNotIn("confirmation_set_labels", serialized_context)
        self.assertNotIn("hidden_return_rank", serialized_context)
        self.assertNotIn("forward_return_labels", serialized_context)
        self.assertNotIn("unpublished_profit_rank", serialized_context)
        self.assertTrue(reviewed_factor["exploratory_candidate"])
        self.assertEqual(reviewed_factor["p_value_method"], "newey_west_hac")
        self.assertEqual(reviewed_factor["passed_windows"], 2)
        self.assertEqual(reviewed_factor["window_count"], 3)
        self.assertEqual(reviewed_factor["worst_window_ic"], -0.01)
        self.assertTrue(reviewed_factor["multi_window_consistent"])

    def test_unknown_factor_key_triggers_one_correction(self) -> None:
        client = SequenceClient([valid_review("invented_factor"), valid_review()])

        response = run_ai_review(research_result(), focus="稳健性", llm=client)

        self.assertTrue(response["ok"])
        self.assertEqual(response["meta"]["attempts"], 2)
        self.assertIn("不存在的因子键", client.calls[1][0][-1]["content"])
        self.assertEqual(response["meta"]["usage"]["total_tokens"], 100)

    @patch("apps.api.domains.factor_research.service.run_factor_research")
    @patch("apps.api.domains.factor_research.service.run_ai_review")
    def test_timeout_returns_actionable_chinese_error(self, ai_review, factor_research) -> None:
        factor_research.return_value = research_result() | {"ok": True}
        ai_review.side_effect = RuntimeError("Request timed out.")

        response = review_factor_research(FactorAiReviewRequest(symbol="AAPL", market="us_stocks"))

        self.assertFalse(response["ok"])
        self.assertIn("超过 120 秒", response["error"])
        self.assertIn("统计结论未受影响", response["error"])


if __name__ == "__main__":
    unittest.main()
