"""GUI 실행 진입점."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from ..console import configure_output
from .main_window import MainWindow


def build_app(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv[:1])
    app.setApplicationName("ytdl4k")
    app.setApplicationDisplayName("ytdl4k")
    # Fusion 은 세 플랫폼에서 같은 모양으로 그려진다 — 화면이 OS 마다 달라지지 않는다.
    app.setStyle("Fusion")
    return app


def run(argv: list[str] | None = None) -> int:
    configure_output()
    app = build_app(argv)
    window = MainWindow()
    window.show()
    watch_clipboard(app, window)
    return app.exec()


def watch_clipboard(app: QApplication, window: MainWindow) -> None:
    """복사해 온 유튜브 주소를 입력칸에 미리 채워 준다."""
    clipboard = app.clipboard()
    if clipboard is None:
        return
    clipboard.dataChanged.connect(lambda: window.paste_from_clipboard(clipboard.text()))
