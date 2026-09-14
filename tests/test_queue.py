"""큐 동작 검증 — UI 없이 돈다."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ytdl4k.app.queue import DownloadQueue
from ytdl4k.app.settings import Settings
from ytdl4k.core.errors import AppError, DownloadCanceled, LoginRequired
from ytdl4k.core.merger import FfmpegTools
from ytdl4k.core.models import TaskState


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeExtractor:
    def __init__(self, info, error: Exception | None = None) -> None:
        self.info = info
        self.error = error
        self.calls: list[str] = []

    def base_options(self) -> dict:
        return {}

    def extract(self, url: str):
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.info


class FakeDownloader:
    """다운로드를 흉내 낸다. 진행률을 몇 번 흘린 뒤 파일 경로를 돌려준다."""

    def __init__(self, task, path: Path, *, block: threading.Event | None = None) -> None:
        self.task = task
        self.path = path
        self.block = block
        self.space_checked = False

    def check_space(self, selection, duration) -> None:
        self.space_checked = True

    def download(self, info, selection, *, cancel_event=None) -> Path:
        if self.block is not None:
            self.block.wait(timeout=5)
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCanceled()
        return self.path


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(output_dir=tmp_path, concurrent_downloads=2)


@pytest.fixture
def ffmpeg() -> FfmpegTools:
    return FfmpegTools(Path("/usr/bin/ffmpeg"), None)


def build_queue(settings, ffmpeg, info_4k, *, error=None, block=None, path=Path("/tmp/out.mp4")):
    extractor = FakeExtractor(info_4k, error)
    seen = []
    queue = DownloadQueue(
        settings,
        ffmpeg=ffmpeg,
        extractor=extractor,
        downloader_factory=lambda task: FakeDownloader(task, path, block=block),
        on_change=seen.append,
    )
    return queue, extractor, seen


def test_task_runs_through_to_done(settings, ffmpeg, info_4k, tmp_path):
    out = tmp_path / "영상.webm"
    queue, extractor, seen = build_queue(settings, ffmpeg, info_4k, path=out)
    task = queue.add("https://youtu.be/x")

    assert wait_for(lambda: task.is_finished)
    assert task.state is TaskState.DONE
    assert task.output_path == out
    assert task.info.title == "샘플 4K 영상"
    assert task.selection.format_spec == "315+251"  # 4K + 오디오
    assert extractor.calls == ["https://youtu.be/x"]
    assert seen, "UI 로 갈 상태 변화 알림이 하나도 없었다"
    queue.shutdown()


def test_progress_reaches_100_on_completion(settings, ffmpeg, info_4k):
    queue, _, _ = build_queue(settings, ffmpeg, info_4k)
    task = queue.add("https://youtu.be/x")
    assert wait_for(lambda: task.state is TaskState.DONE)
    assert task.progress.percent == 100.0
    queue.shutdown()


def test_login_required_is_surfaced_not_swallowed(settings, ffmpeg, info_4k):
    queue, _, _ = build_queue(settings, ffmpeg, info_4k, error=LoginRequired())
    task = queue.add("https://youtu.be/x")

    assert wait_for(lambda: task.is_finished)
    assert task.state is TaskState.FAILED
    assert "로그인이 필요한 영상입니다" in task.error.message
    assert "--cookies-from-browser" in task.error.hint
    queue.shutdown()


def test_unexpected_error_fails_only_that_task(settings, ffmpeg, info_4k):
    """예상 못 한 오류 하나가 큐 전체를 멈추면 안 된다."""
    queue, _, _ = build_queue(settings, ffmpeg, info_4k, error=RuntimeError("알 수 없는 오류"))
    first = queue.add("https://youtu.be/a")
    assert wait_for(lambda: first.is_finished)
    assert first.state is TaskState.FAILED
    assert isinstance(first.error, AppError)

    queue.extractor.error = None
    second = queue.add("https://youtu.be/b")
    assert wait_for(lambda: second.state is TaskState.DONE)
    queue.shutdown()


def test_cancel_marks_the_task_canceled(settings, ffmpeg, info_4k):
    block = threading.Event()
    queue, _, _ = build_queue(settings, ffmpeg, info_4k, block=block)
    task = queue.add("https://youtu.be/x")

    assert wait_for(lambda: task.state is TaskState.DOWNLOADING)
    queue.cancel(task.id)
    block.set()

    assert wait_for(lambda: task.is_finished)
    assert task.state is TaskState.CANCELED
    queue.shutdown()


def test_remove_takes_it_off_the_list(settings, ffmpeg, info_4k):
    queue, _, _ = build_queue(settings, ffmpeg, info_4k)
    task = queue.add("https://youtu.be/x")
    assert wait_for(lambda: task.is_finished)

    queue.remove(task.id)
    assert queue.find(task.id) is None
    assert queue.tasks == []
    queue.shutdown()


def test_clear_finished_keeps_running_tasks(settings, ffmpeg, info_4k):
    block = threading.Event()
    queue, _, _ = build_queue(settings, ffmpeg, info_4k, block=block)
    running = queue.add("https://youtu.be/running")
    assert wait_for(lambda: running.state is TaskState.DOWNLOADING)

    done = queue.add("https://youtu.be/done")
    done.state = TaskState.DONE

    queue.clear_finished()
    assert [t.id for t in queue.tasks] == [running.id]
    block.set()
    queue.shutdown()


def test_counts_summarize_the_queue(settings, ffmpeg, info_4k):
    queue, _, _ = build_queue(settings, ffmpeg, info_4k)
    queue.add("https://youtu.be/x")
    assert wait_for(lambda: all(t.is_finished for t in queue.tasks))
    assert queue.counts()[TaskState.DONE] == 1
    queue.shutdown()


def test_status_text_is_korean(settings, ffmpeg, info_4k):
    queue, _, _ = build_queue(settings, ffmpeg, info_4k)
    task = queue.add("https://youtu.be/x")
    assert wait_for(lambda: task.is_finished)
    assert task.status_text() == "완료"
    assert task.title == "샘플 4K 영상"
    queue.shutdown()


def test_without_ffmpeg_it_falls_back_to_progressive(settings, info_4k):
    """ffmpeg 이 없으면 실패시키지 않고 받을 수 있는 것을 받는다."""
    queue, _, _ = build_queue(settings, None, info_4k)
    task = queue.add("https://youtu.be/x")
    assert wait_for(lambda: task.is_finished)
    assert task.state is TaskState.DONE
    assert task.selection.format_spec == "18"
    queue.shutdown()
