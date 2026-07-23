"""PA Agent utility package.

NOTE: ``event_bus`` pulls in PyQt6 (QObject / pyqtSignal) and must NOT be
imported at package-init time — otherwise the pure-Python helpers in
``pa_agent.util.trade_metrics`` become unusable from non-GUI contexts
(e.g. the Streamlit web workbench). Import ``event_bus`` explicitly where
the Qt runtime is available.
"""

from pa_agent.util.logging import configure_logging, update_api_key
from pa_agent.util.threading import CancelToken, OrchestratorEvent

__all__ = [
    "CancelToken",
    "OrchestratorEvent",
    "configure_logging",
    "update_api_key",
]
