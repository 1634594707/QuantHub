"""Tests for support/resistance chart level selection."""
from __future__ import annotations

from pa_agent.gui.support_resistance import chart_levels_from_stage1_diagnosis


def test_chart_uses_farthest_support_and_resistance() -> None:
    stage1 = {
        "support_levels": ["4174.938", "4139", "4121"],
        "resistance_levels": ["4178.69", "4200", "4221"],
    }
    levels = chart_levels_from_stage1_diagnosis(stage1)
    assert len(levels) == 2
    support = next(l for l in levels if l.kind == "support")
    resistance = next(l for l in levels if l.kind == "resistance")
    assert support.price == 4121.0
    assert resistance.price == 4221.0
    assert support.label == "支撑"
    assert resistance.label == "阻力"
