"""다운로드 큐.

GUI 도 CLI 도 아닌 순수 파이썬이다. Qt 를 모르기 때문에 UI 없이 테스트할 수 있고,
나중에 CLI 의 일괄 다운로드도 이 큐를 그대로 쓸 수 있다.

UI 는 ``on_change`` 콜백으로 상태 변화를 받는다. 콜백은 **작업 스레드에서** 불리므로
UI 쪽에서 스레드 경계를 넘기는 책임은 UI 계층(gui/bridge.py)이 진다.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from ..core.downloader import Downloader, Progress
from ..core.errors import AppError, DownloadCanceled
from ..core.extractor import Extractor, YtDlpExtractor
from ..core.formats import Selection, select
from ..core.merger import FfmpegTools
from ..core.models import TaskState, VideoInfo
from .settings import Settings

_ids = itertools.count(1)


@dataclass
class DownloadTask:
    url: str
    id: str = field(default_factory=lambda: f"t{next(_ids)}")
    state: TaskState = TaskState.PENDING
    info: VideoInfo | None = None
    selection: Selection | None = None
    progress: Progress = field(default_factory=lambda: Progress(stage=TaskState.PENDING))
    output_path: Path | None = None
    error: AppError | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def title(self) -> str:
        return self.info.title if self.info else self.url

    @property
    def quality(self) -> str:
        return self.selection.describe() if self.selection else "—"

    @property
    def is_finished(self) -> bool:
        return self.state in (TaskState.DONE, TaskState.FAILED, TaskState.CANCELED)

    def status_text(self) -> str:
        return {
            TaskState.PENDING: "대기 중",
            TaskState.EXTRACTING: "정보 읽는 중",
            TaskState.DOWNLOADING: "받는 중",
            TaskState.MERGING: "합치는 중",
            TaskState.DONE: "완료",
            TaskState.FAILED: "실패",
            TaskState.CANCELED: "취소됨",
        }[self.state]


ChangeCallback = Callable[[DownloadTask], None]


class DownloadQueue:
    """여러 URL 을 동시에 제한된 개수만큼 처리한다."""

    def __init__(
        self,
        settings: Settings,
        *,
        ffmpeg: FfmpegTools | None = None,
        extractor: Extractor | None = None,
        downloader_factory: Callable[[DownloadTask], Downloader] | None = None,
        on_change: ChangeCallback | None = None,
    ) -> None:
        self.settings = settings
        self.ffmpeg = ffmpeg
        self.extractor = extractor or YtDlpExtractor(cookies_from_browser=settings.cookies_from_browser)
        self._downloader_factory = downloader_factory or self._build_downloader
        self.on_change = on_change
        self.tasks: list[DownloadTask] = []
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, settings.concurrent_downloads), thread_name_prefix="ytdl4k"
        )

    # ------------------------------------------------------------------ 공개 API

    def add(self, url: str) -> DownloadTask:
        task = DownloadTask(url=url.strip())
        with self._lock:
            self.tasks.append(task)
            self._futures[task.id] = self._pool.submit(self._run, task)
        self._notify(task)
        return task

    def cancel(self, task_id: str) -> None:
        task = self.find(task_id)
        if task is None or task.is_finished:
            return
        task.cancel.set()
        future = self._futures.get(task_id)
        if future is not None and future.cancel():
            # 아직 시작도 안 한 작업은 그 자리에서 취소로 끝낸다.
            self._finish(task, TaskState.CANCELED, error=DownloadCanceled())

    def remove(self, task_id: str) -> None:
        """목록에서 뺀다. 진행 중이면 취소부터."""
        self.cancel(task_id)
        with self._lock:
            self.tasks = [t for t in self.tasks if t.id != task_id]
            self._futures.pop(task_id, None)

    def clear_finished(self) -> None:
        with self._lock:
            self.tasks = [t for t in self.tasks if not t.is_finished]

    def find(self, task_id: str) -> DownloadTask | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def counts(self) -> dict[TaskState, int]:
        counts: dict[TaskState, int] = {}
        for task in self.tasks:
            counts[task.state] = counts.get(task.state, 0) + 1
        return counts

    def shutdown(self, *, wait: bool = False) -> None:
        for task in self.tasks:
            task.cancel.set()
        self._pool.shutdown(wait=wait, cancel_futures=True)

    # ------------------------------------------------------------------ 작업 본체

    def _run(self, task: DownloadTask) -> None:
        try:
            self._set_state(task, TaskState.EXTRACTING)
            task.info = self.extractor.extract(task.url)
            self._notify(task)

            task.selection = select(task.info, self.settings.target(), can_merge=self.ffmpeg is not None)
            self._set_state(task, TaskState.DOWNLOADING)

            downloader = self._downloader_factory(task)
            downloader.check_space(task.selection, task.info.duration)
            task.output_path = downloader.download(task.info, task.selection, cancel_event=task.cancel)
            self._finish(task, TaskState.DONE)
        except DownloadCanceled as err:
            self._finish(task, TaskState.CANCELED, error=err)
        except AppError as err:
            self._finish(task, TaskState.FAILED, error=err)
        except Exception as err:  # 예상 못 한 오류로 큐 전체가 멈추면 안 된다
            self._finish(task, TaskState.FAILED, error=AppError(str(err)))

    def _build_downloader(self, task: DownloadTask) -> Downloader:
        return Downloader(
            output_dir=self.settings.output_dir,
            base_options=getattr(self.extractor, "base_options", dict)(),
            filename_template=self.settings.filename_template,
            ffmpeg=self.ffmpeg,
            concurrent_fragments=self.settings.concurrent_fragments,
            overwrite=self.settings.overwrite,
            on_progress=lambda progress: self._on_progress(task, progress),
        )

    def _on_progress(self, task: DownloadTask, progress: Progress) -> None:
        task.progress = progress
        if progress.stage in (TaskState.DOWNLOADING, TaskState.MERGING):
            task.state = progress.stage
        self._notify(task)

    def _set_state(self, task: DownloadTask, state: TaskState) -> None:
        task.state = state
        self._notify(task)

    def _finish(self, task: DownloadTask, state: TaskState, *, error: AppError | None = None) -> None:
        task.state = state
        task.error = error
        if state is TaskState.DONE:
            task.progress = Progress(stage=TaskState.DONE, percent=100.0)
        self._notify(task)

    def _notify(self, task: DownloadTask) -> None:
        if self.on_change is not None:
            self.on_change(task)
