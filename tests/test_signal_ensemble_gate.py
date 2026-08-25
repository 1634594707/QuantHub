from __future__ import annotations

import pytest

from apps.api.domains.signals.schemas import PublishSignalRequest
from apps.api.domains.signals.service import publish


def test_ensemble_signal_requires_persisted_research_context() -> None:
    request = PublishSignalRequest(
        symbol="600519",
        market="a_shares",
        direction="buy",
        score=0.8,
        confidence=0.7,
        source="ensemble",
    )

    with pytest.raises(ValueError, match="ENSEMBLE_RESEARCH_CONTEXT_REQUIRED"):
        publish(request)
