"""Application entry point for PA Agent."""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    # Early diagnostics before Qt / heavy imports: crash dumps + file logging.
    from pa_agent.util.crash_diagnostics import enable_crash_diagnostics, log_startup_diagnostics
    from pa_agent.util.logging import configure_logging

    enable_crash_diagnostics()
    configure_logging()
    log_startup_diagnostics()

    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("PA Agent")

    from pa_agent.gui.theme import apply_theme

    apply_theme(app)

    logger.info("PA Agent starting up")

    # Bootstrap all components (settings, data source, AI client, etc.)
    from pa_agent.app_context import AppContext

    ctx = AppContext.bootstrap()

    # Update logging with the real API key now that settings are loaded
    if ctx.settings is not None:
        from pa_agent.util.logging import configure_logging

        configure_logging(api_key=ctx.settings.provider.api_key)
        from pa_agent.util.crash_diagnostics import log_startup_diagnostics

        log_startup_diagnostics()

    # Build and show the main window
    from pa_agent.gui.main_window import MainWindow

    window = MainWindow(ctx)
    window.show()

    logger.info("Main window shown")
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
