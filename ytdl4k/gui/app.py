"""GUI 실행 진입점."""

from __future__ import annotations

import os
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
    args = list(sys.argv if argv is None else argv)
    if "--smoke" in args:
        return smoke()

    configure_output()
    app = build_app(argv)
    window = MainWindow()
    window.show()
    watch_clipboard(app, window)
    return app.exec()


def smoke() -> int:
    """창이 뜨는지만 확인하고 바로 끝낸다 — 묶은 실행 파일 점검용."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    configure_output()
    app = build_app([])
    window = MainWindow()
    window.show()
    app.processEvents()
    if sys.stdout is not None:  # 윈도우 창 모드에서는 표준 출력이 없다
        print(f"창 준비됨 · {window.statusBar().currentMessage()}")
    window.queue.shutdown()
    return 0


def watch_clipboard(app: QApplication, window: MainWindow) -> None:
    """복사해 온 유튜브 주소를 입력칸에 미리 채워 준다."""
    clipboard = app.clipboard()
    if clipboard is None:
        return
    clipboard.dataChanged.connect(lambda: window.paste_from_clipboard(clipboard.text()))
