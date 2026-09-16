"""메인 창.

화면 구성은 사용자가 하는 순서를 그대로 따른다:
주소를 넣고 → 화질을 고르고 → 받고 → 목록에서 진행을 본다.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..app.queue import DownloadQueue, DownloadTask
from ..app.settings import Settings
from ..core.extractor import YtDlpExtractor
from ..core.merger import find_ffmpeg
from ..core.models import CodecPolicy, TaskState, ThumbnailMode
from .bridge import QueueSignals
from .model import PROGRESS, TITLE, ProgressDelegate, QueueModel

# 유튜브 주소로 보이는지. 엄격하게 막기보다 '붙여넣기 감지' 용도다.
YOUTUBE_URL = re.compile(r"https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/\S+", re.I)

QUALITY_CHOICES: list[tuple[str, int | None]] = [
    ("최고 화질", None),
    ("4K (2160p)", 2160),
    ("1440p", 1440),
    ("1080p", 1080),
    ("720p", 720),
]

CODEC_CHOICES: list[tuple[str, CodecPolicy]] = [
    ("화질 우선", CodecPolicy.QUALITY),
    ("용량 우선", CodecPolicy.EFFICIENCY),
    ("호환성 우선", CodecPolicy.COMPATIBILITY),
]

THUMBNAIL_CHOICES: list[tuple[str, ThumbnailMode]] = [
    ("안 함", ThumbnailMode.NONE),
    ("영상에 넣기", ThumbnailMode.EMBED),
    ("그림 파일로", ThumbnailMode.FILE),
]

# 연령 제한·멤버십 영상은 로그인된 브라우저의 쿠키가 있어야 목록조차 보이지 않는다.
# 오류만 띄우고 손쓸 방법을 주지 않으면 막다른 길이 되므로 화면에서 고르게 한다.
COOKIE_CHOICES: list[tuple[str, str | None]] = [
    ("로그인 안 함", None),
    ("Chrome", "chrome"),
    ("Edge", "edge"),
    ("Firefox", "firefox"),
    ("Safari", "safari"),
    ("Brave", "brave"),
]


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None, *, queue: DownloadQueue | None = None):
        super().__init__()
        self.settings = settings or Settings.load()
        self.ffmpeg = find_ffmpeg()
        self.signals = QueueSignals()
        self.queue = queue or DownloadQueue(
            self.settings, ffmpeg=self.ffmpeg, on_change=self.signals.task_changed.emit
        )
        self.queue.on_change = self.signals.task_changed.emit

        self.setWindowTitle("ytdl4k — 유튜브 4K 다운로더")
        self.resize(940, 560)
        self._build()
        self._connect()
        self._apply_settings_to_controls()
        self._update_status()

    # ------------------------------------------------------------------ 화면 구성

    def _build(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)

        # 1) 주소 입력
        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("유튜브 주소를 붙여넣으세요")
        self.url_edit.setClearButtonEnabled(True)
        self.add_button = QPushButton("받기")
        self.add_button.setDefault(True)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.add_button)
        outer.addLayout(url_row)

        # 2) 화질·코덱 선택
        options = QHBoxLayout()
        options.setSpacing(8)
        self.quality_box = QComboBox()
        for label, height in QUALITY_CHOICES:
            self.quality_box.addItem(label, height)
        self.codec_box = QComboBox()
        for label, policy in CODEC_CHOICES:
            # Qt 를 거치면 StrEnum 이 평범한 str 로 돌아온다. 값으로 넣고 읽을 때 되돌린다.
            self.codec_box.addItem(label, policy.value)
        self.audio_only = QCheckBox("소리만")
        self.thumbnail_box = QComboBox()
        for label, mode in THUMBNAIL_CHOICES:
            self.thumbnail_box.addItem(label, mode.value)
        self.thumbnail_box.setToolTip(
            "영상에 넣으면 플레이어·파일 탐색기에서 표지로 보입니다.\n"
            "webm 에는 표지를 넣을 수 없어 mkv 로 담깁니다(화질 손실 없음)."
        )
        self.cookie_box = QComboBox()
        for label, browser in COOKIE_CHOICES:
            self.cookie_box.addItem(label, browser)
        self.cookie_box.setToolTip("연령 제한·멤버십 영상은 로그인한 브라우저를 골라야 받을 수 있습니다")
        options.addWidget(QLabel("화질"))
        options.addWidget(self.quality_box)
        options.addSpacing(8)
        options.addWidget(QLabel("우선순위"))
        options.addWidget(self.codec_box)
        options.addSpacing(8)
        options.addWidget(self.audio_only)
        options.addSpacing(8)
        options.addWidget(QLabel("썸네일"))
        options.addWidget(self.thumbnail_box)
        options.addSpacing(8)
        options.addWidget(QLabel("로그인"))
        options.addWidget(self.cookie_box)
        options.addStretch(1)
        self.folder_label = QLabel()
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.folder_button = QPushButton("저장 위치")
        options.addWidget(self.folder_label)
        options.addWidget(self.folder_button)
        outer.addLayout(options)

        # 3) 목록
        self.model = QueueModel(self.queue)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(PROGRESS, ProgressDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(TITLE, QHeaderView.Stretch)
        for column in range(1, self.model.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        # 진행률은 한눈에 읽히는 것이 핵심이라 머리글 너비에 맞춰 눌리면 안 된다.
        header.setSectionResizeMode(PROGRESS, QHeaderView.Fixed)
        self.table.setColumnWidth(PROGRESS, 132)
        self.table.verticalHeader().setDefaultSectionSize(30)
        outer.addWidget(self.table, 1)

        # 4) 상태 · 동작
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.cancel_button = QPushButton("취소")
        self.open_button = QPushButton("폴더 열기")
        self.clear_button = QPushButton("완료 항목 지우기")
        for button in (self.cancel_button, self.open_button):
            button.setEnabled(False)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.open_button)
        bottom.addWidget(self.clear_button)
        bottom.addStretch(1)
        self.summary_label = QLabel()
        bottom.addWidget(self.summary_label)
        outer.addLayout(bottom)

        # 5) 선택한 항목의 안내·오류 (원인과 다음 행동을 함께 보여 준다)
        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        self.detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.detail_label.setVisible(False)
        outer.addWidget(self.detail_label)

        self.setCentralWidget(central)
        self.statusBar().showMessage(self._ffmpeg_message())

    def _connect(self) -> None:
        self.add_button.clicked.connect(self.add_current_url)
        self.url_edit.returnPressed.connect(self.add_current_url)
        self.folder_button.clicked.connect(self.choose_folder)
        self.cancel_button.clicked.connect(self.cancel_selected)
        self.open_button.clicked.connect(self.open_selected_folder)
        self.clear_button.clicked.connect(self.clear_finished)
        self.quality_box.currentIndexChanged.connect(self._store_settings)
        self.codec_box.currentIndexChanged.connect(self._store_settings)
        self.audio_only.toggled.connect(self._store_settings)
        self.thumbnail_box.currentIndexChanged.connect(self._store_settings)
        self.cookie_box.currentIndexChanged.connect(self._on_cookie_changed)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self.signals.task_changed.connect(self._on_task_changed)

    # ------------------------------------------------------------------ 동작

    def add_current_url(self) -> None:
        self.add_url(self.url_edit.text())

    def add_url(self, url: str) -> DownloadTask | None:
        url = url.strip()
        if not url:
            return None
        if not url.lower().startswith(("http://", "https://")):
            self._show_detail("주소가 아닙니다.", "유튜브 영상 주소를 붙여넣어 주세요.", error=True)
            return None

        self._store_settings()
        task = self.queue.add(url)
        self.model.task_added()
        self.url_edit.clear()
        self._update_status()
        return task

    def cancel_selected(self) -> None:
        task = self._selected_task()
        if task is not None:
            self.queue.cancel(task.id)

    def clear_finished(self) -> None:
        self.queue.clear_finished()
        self.model.reload()
        self._update_status()

    def open_selected_folder(self) -> None:
        task = self._selected_task()
        folder = task.output_path.parent if task and task.output_path else self.settings.output_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "저장 위치 선택", str(self.settings.output_dir))
        if chosen:
            self.set_output_dir(Path(chosen))

    def set_output_dir(self, folder: Path) -> None:
        self.settings.output_dir = folder
        self.queue.settings = self.settings
        self.folder_label.setText(self._folder_text())
        self.folder_label.setToolTip(str(folder))
        self._store_settings()

    def paste_from_clipboard(self, text: str) -> bool:
        """클립보드에 유튜브 주소가 들어오면 입력칸을 미리 채워 둔다.

        자동으로 받기 시작하지는 않는다 — 사용자가 의도하지 않은 다운로드가
        시작되는 것만큼 성가신 일도 없다.
        """
        if not YOUTUBE_URL.fullmatch(text.strip()) or self.url_edit.text().strip():
            return False
        self.url_edit.setText(text.strip())
        return True

    # ------------------------------------------------------------------ 상태 반영

    def _on_task_changed(self, task: DownloadTask) -> None:
        self.model.task_changed(task)
        self._update_status()
        selected = self._selected_task()
        if selected is not None and selected.id == task.id:
            self._show_task_detail(task)

    def _on_selection_changed(self) -> None:
        task = self._selected_task()
        self.cancel_button.setEnabled(task is not None and not task.is_finished)
        self.open_button.setEnabled(task is not None and task.output_path is not None)
        if task is None:
            self.detail_label.setVisible(False)
        else:
            self._show_task_detail(task)

    def _show_task_detail(self, task: DownloadTask) -> None:
        if task.error is not None:
            self._show_detail(task.error.message, task.error.hint, error=True)
        elif task.output_path is not None:
            hint = str(task.output_path)
            if task.note:
                hint = f"{task.note}<br>{hint}"
            self._show_detail("저장 완료", hint)
        elif task.note:
            self._show_detail("받는 중", task.note)
        elif task.selection is not None:
            self._show_detail("받는 중", task.selection.describe())
        else:
            self.detail_label.setVisible(False)

    def _show_detail(self, message: str, hint: str | None = None, *, error: bool = False) -> None:
        color = "#B3261E" if error else "palette(text)"
        text = f"<b>{message}</b>"
        if hint:
            text += f"<br><span style='color:palette(mid)'>{hint}</span>"
        self.detail_label.setText(text)
        self.detail_label.setStyleSheet(f"color:{color}")
        self.detail_label.setVisible(True)

    def _update_status(self) -> None:
        counts = self.queue.counts()
        running = counts.get(TaskState.DOWNLOADING, 0) + counts.get(TaskState.MERGING, 0)
        waiting = counts.get(TaskState.PENDING, 0) + counts.get(TaskState.EXTRACTING, 0)
        done = counts.get(TaskState.DONE, 0)
        failed = counts.get(TaskState.FAILED, 0)
        parts = [f"받는 중 {running}", f"대기 {waiting}", f"완료 {done}"]
        if failed:
            parts.append(f"실패 {failed}")
        self.summary_label.setText(" · ".join(parts))
        self._on_selection_changed()

    def _selected_task(self) -> DownloadTask | None:
        rows = self.table.selectionModel().selectedRows()
        return self.model.task_at(rows[0].row()) if rows else None

    # ------------------------------------------------------------------ 설정

    def _apply_settings_to_controls(self) -> None:
        index = self.quality_box.findData(self.settings.max_height)
        self.quality_box.setCurrentIndex(index if index >= 0 else 1)
        index = self.codec_box.findData(CodecPolicy(self.settings.codec_policy).value)
        self.codec_box.setCurrentIndex(max(0, index))
        self.audio_only.setChecked(self.settings.audio_only)
        index = self.thumbnail_box.findData(ThumbnailMode(self.settings.thumbnail).value)
        self.thumbnail_box.setCurrentIndex(max(0, index))
        index = self.cookie_box.findData(self.settings.cookies_from_browser)
        self.cookie_box.setCurrentIndex(max(0, index))
        self.folder_label.setText(self._folder_text())
        self.folder_label.setToolTip(str(self.settings.output_dir))

    def _on_cookie_changed(self) -> None:
        """쿠키 설정은 추출기를 새로 만들어야 반영된다."""
        self.settings.cookies_from_browser = self.cookie_box.currentData()
        self.queue.extractor = YtDlpExtractor(cookies_from_browser=self.settings.cookies_from_browser)
        self._store_settings()

    def _store_settings(self) -> None:
        self.settings.max_height = self.quality_box.currentData()
        self.settings.codec_policy = CodecPolicy(self.codec_box.currentData())
        self.settings.audio_only = self.audio_only.isChecked()
        self.settings.thumbnail = ThumbnailMode(self.thumbnail_box.currentData())
        self.queue.settings = self.settings

    def _folder_text(self) -> str:
        folder = str(self.settings.output_dir)
        return folder if len(folder) <= 38 else "…" + folder[-37:]

    def _ffmpeg_message(self) -> str:
        if self.ffmpeg is None:
            return "ffmpeg 없음 — 1080p 를 넘는 화질은 받을 수 없습니다"
        return f"준비됨 · 합치기 도구: {self.ffmpeg.ffmpeg}"

    # ------------------------------------------------------------------ 종료

    def closeEvent(self, event) -> None:
        self._store_settings()
        # 설정 저장에 실패해도 종료는 막지 않는다.
        with contextlib.suppress(OSError):
            self.settings.save()
        self.queue.shutdown()
        super().closeEvent(event)
