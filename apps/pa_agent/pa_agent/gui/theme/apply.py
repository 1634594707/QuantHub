"""Apply the global application theme."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QApplication

_QSS_PATH = Path(__file__).with_name("dark.qss")


def apply_theme(app: QApplication) -> None:
    """Load dark.qss and set application-wide palette hints."""
    if _QSS_PATH.is_file():
        app.setStyleSheet(_QSS_PATH.read_text(encoding="utf-8"))
    app.setStyle("Fusion")
