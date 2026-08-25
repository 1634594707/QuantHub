from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from apps.api.domains.simulation.risk import PaperOrderIntent
from apps.api.domains.simulation.schemas import (
    SimulationFillCreate,
    SimulationOrderCreate,
    SimulationOrderPreviewRequest,
)


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_simulation_order_create_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValidationError):
        SimulationOrderCreate(
            symbol="600519",
            market="a_shares",
            side="buy",
            quantity=value,
        )


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_simulation_preview_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValidationError):
        SimulationOrderPreviewRequest(
            symbol="600519",
            market="a_shares",
            side="buy",
            quantity=value,
        )


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_simulation_fill_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValidationError):
        SimulationFillCreate(price=value)


def test_paper_order_intent_rejects_infinite_quantity() -> None:
    with pytest.raises(ValidationError):
        PaperOrderIntent(
            intent_id="intent-1",
            account_id="paper",
            symbol="600519",
            market="a_shares",
            side="buy",
            order_type="market",
            quantity=math.inf,
        )
