"""다운로드 목록 표 모델."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionProgressBar

from ..app.queue import DownloadQueue, DownloadTask
from ..core.models import TaskState

# Qt 가 넘겨 주는 '부모 없음' 인덱스. 값 타입이라 QApplication 없이도 만들 수 있다.
_ROOT = QModelIndex()

COLUMNS = ("제목", "화질", "상태", "진행률", "속도")
TITLE, QUALITY, STATUS, PROGRESS, SPEED = range(len(COLUMNS))


def format_speed(bps: float | None) -> str:
    if not bps:
        return "—"
    if bps >= 2**20:
        return f"{bps / 2**20:.1f} MB/s"
    return f"{bps / 2**10:.0f} KB/s"


def format_eta(seconds: int | None) -> str:
    if not seconds:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}분 {secs}초 남음" if minutes else f"{secs}초 남음"


def _shows_bar(task: DownloadTask) -> bool:
    return task.state in (TaskState.DOWNLOADING, TaskState.MERGING, TaskState.DONE)


class QueueModel(QAbstractTableModel):
    def __init__(self, queue: DownloadQueue) -> None:
        super().__init__()
        self.queue = queue

    # ------------------------------------------------------------------ Qt 인터페이스

    def rowCount(self, parent=_ROOT) -> int:
        return 0 if parent.isValid() else len(self.queue.tasks)

    def columnCount(self, parent=_ROOT) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section: int, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        task = self.queue.tasks[index.row()]
        column = index.column()

        if role == Qt.DisplayRole:
            return self._text(task, column)
        if role == Qt.UserRole and column == PROGRESS:
            # 아직 시작하지 않았거나 끝나 버린 작업에 빈 막대를 두면 눈만 어지럽다.
            return task.progress.percent if _shows_bar(task) else None
        if role == Qt.ToolTipRole:
            return self._tooltip(task)
        if role == Qt.TextAlignmentRole and column in (PROGRESS, SPEED):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    # ------------------------------------------------------------------ 내용

    @staticmethod
    def _text(task: DownloadTask, column: int) -> str:
        if column == TITLE:
            return task.title
        if column == QUALITY:
            return task.quality
        if column == STATUS:
            return task.status_text()
        if column == PROGRESS:
            return f"{task.progress.percent:.0f}%" if _shows_bar(task) else "—"
        if column == SPEED:
            if task.state is TaskState.DOWNLOADING:
                return format_speed(task.progress.speed_bps)
            return "—"
        return ""

    @staticmethod
    def _tooltip(task: DownloadTask) -> str:
        if task.error is not None:
            return task.error.full_message
        if task.output_path is not None:
            return str(task.output_path)
        eta = format_eta(task.progress.eta_s)
        return f"{task.url}\n{eta}" if eta else task.url

    # ------------------------------------------------------------------ 갱신

    def task_at(self, row: int) -> DownloadTask | None:
        return self.queue.tasks[row] if 0 <= row < len(self.queue.tasks) else None

    def row_of(self, task: DownloadTask) -> int:
        return next((i for i, t in enumerate(self.queue.tasks) if t.id == task.id), -1)

    def task_added(self) -> None:
        last = len(self.queue.tasks) - 1
        self.beginInsertRows(_ROOT, last, last)
        self.endInsertRows()

    def task_changed(self, task: DownloadTask) -> None:
        row = self.row_of(task)
        if row < 0:
            return
        self.dataChanged.emit(
            self.index(row, 0), self.index(row, len(COLUMNS) - 1), [Qt.DisplayRole, Qt.UserRole]
        )

    def reload(self) -> None:
        self.beginResetModel()
        self.endResetModel()


class ProgressDelegate(QStyledItemDelegate):
    """진행률 칸을 막대로 그린다. 숫자만 보는 것보다 한눈에 들어온다."""

    def paint(self, painter, option, index) -> None:
        percent = index.data(Qt.UserRole)
        if percent is None:
            super().paint(painter, option, index)
            return

        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(4, 6, -4, -6)
        bar.minimum = 0
        bar.maximum = 100
        bar.progress = int(max(0, min(100, percent)))
        bar.text = f"{bar.progress}%"
        bar.textVisible = True
        bar.palette = option.palette
        QApplication.style().drawControl(QStyle.CE_ProgressBar, bar, painter)
