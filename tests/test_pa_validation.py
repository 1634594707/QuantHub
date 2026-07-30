from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from strategies.ai_analysis.pa_agent.two_stage import _call_with_quality_gate
from strategies.ai_analysis.pa_agent.validation import (
    validate_bar_references,
    validate_stage1,
    validate_stage2,
)


def stage1_payload() -> dict:
    return {
        "cycle_position": "normal_channel",
        "alternative_cycle_position": None,
        "direction": "bullish",
        "gate_result": "proceed",
        "diagnosis_confidence": 72,
        "key_levels": {"support": [98.0], "resistance": [106.0]},
        "gate_trace": [{"node_id": "1.2", "answer": "是"}],
    }


def no_order_payload() -> dict:
    return {
        "decision": {
            "order_type": "不下单",
            "order_direction": None,
            "entry_price": None,
            "stop_loss_price": None,
            "take_profit_price": None,
            "take_profit_price_2": None,
            "estimated_win_rate": None,
            "reasoning": "等待结构确认",
            "trade_confidence": 20,
        },
        "terminal": {"outcome": "wait"},
        "next_bar_prediction": {
            "unpredictable": True,
            "direction": None,
            "probabilities": None,
        },
    }


class SequenceClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[dict[str, str]]] = []
        self._provider = "test"

    def chat(self, messages, **_kwargs):
        self.calls.append(messages)
        content = self.responses.pop(0)
        return SimpleNamespace(
            content=content,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )


class PaValidationTests(unittest.TestCase):
    def test_stage2_rejects_no_order_with_price_fields(self) -> None:
        payload = no_order_payload()
        payload["decision"]["entry_price"] = 100

        report = validate_stage2(payload, stage1_payload())

        self.assertFalse(report.valid)
        self.assertIn("no_order_invariant", {issue.code for issue in report.issues})

    def test_stage2_rejects_invalid_geometry_and_probability_sum(self) -> None:
        payload = {
            "decision": {
                "order_type": "限价单",
                "order_direction": "做多",
                "entry_price": 100,
                "stop_loss_price": 102,
                "take_profit_price": 104,
                "take_profit_price_2": 108,
                "estimated_win_rate": 60,
                "reasoning": "测试",
                "trade_confidence": 65,
            },
            "terminal": {"outcome": "trade"},
            "next_bar_prediction": {
                "unpredictable": False,
                "direction": "bullish",
                "probabilities": {"bullish": 80, "bearish": 30, "neutral": 10},
            },
        }

        report = validate_stage2(payload, stage1_payload())
        codes = {issue.code for issue in report.issues}

        self.assertFalse(report.valid)
        self.assertIn("price_geometry", codes)
        self.assertIn("probability_sum", codes)

    def test_valid_no_order_plan_passes(self) -> None:
        report = validate_stage2(no_order_payload(), stage1_payload())
        self.assertTrue(report.valid)

    def test_quality_gate_retries_with_field_feedback(self) -> None:
        invalid = {**stage1_payload(), "direction": "up"}
        valid = stage1_payload()
        client = SequenceClient([json.dumps(invalid), json.dumps(valid)])

        parsed, _, usage, report, attempts = _call_with_quality_gate(
            client,
            [{"role": "system", "content": "schema"}],
            stage="stage1",
            validator=validate_stage1,
            max_validation_retries=1,
        )

        self.assertEqual(parsed, valid)
        self.assertTrue(report.valid)
        self.assertEqual(attempts, 2)
        self.assertEqual(usage["total_tokens"], 30)
        self.assertIn("direction", client.calls[1][-1]["content"])
        self.assertIn("只修正", client.calls[1][-1]["content"])

    def test_bar_reference_rejects_window_overflow(self) -> None:
        payload = {**stage1_payload(), "gate_trace": [{"node_id": "1.2", "bar_range": "K8-K1"}]}
        self.assertTrue(validate_bar_references(payload, stage="stage1", max_bar=8).valid)

        payload["gate_trace"][0]["bar_range"] = "K9-K1"
        report = validate_bar_references(payload, stage="stage1", max_bar=8)

        self.assertFalse(report.valid)
        self.assertIn("bar_reference_range", {issue.code for issue in report.issues})

    def test_bar_reference_missing_range_is_warning(self) -> None:
        payload = {**no_order_payload(), "decision_trace": [{"node_id": "4.1"}]}
        report = validate_bar_references(payload, stage="stage2", max_bar=12)

        self.assertTrue(report.valid)
        self.assertEqual(report.issues[0].severity, "warning")
        self.assertEqual(report.issues[0].code, "bar_reference")


if __name__ == "__main__":
    unittest.main()
