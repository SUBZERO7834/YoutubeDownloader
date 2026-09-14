"""큐(작업 스레드) → Qt(메인 스레드) 신호 전달.

DownloadQueue 는 Qt 를 모른다. 그래서 큐의 콜백을 Qt 시그널로 바꿔 주는 얇은 층을
둔다. 시그널은 스레드 경계를 큐잉해서 넘겨 주므로, 위젯은 항상 메인 스레드에서만
건드려진다 — 이것을 지키지 않으면 Qt 앱은 조용히 깨진다.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class QueueSignals(QObject):
    task_changed = Signal(object)  # DownloadTask
