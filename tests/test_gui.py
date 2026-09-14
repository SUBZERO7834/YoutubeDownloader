"""화면 동작 검증.

실제 창을 띄우지 않고(offscreen) 위젯을 만들어 조작한다. 클릭 한 번으로 확인하던
것들을 자동으로 확인해 둔다 — 화면은 눈으로만 확인하면 금방 회귀한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6", reason="GUI 의존성이 없는 환경에서는 건너뛴다")

from PySide6.QtCore import Qt  # noqa: E402

from ytdl4k.app.queue import DownloadQueue, DownloadTask  # noqa: E402
from ytdl4k.app.settings import Settings  # noqa: E402
from ytdl4k.core.downloader import Progress  # noqa: E402
from ytdl4k.core.errors import LoginRequired  # noqa: E402
from ytdl4k.core.models import CodecPolicy, TaskState  # noqa: E402
from ytdl4k.gui.app import build_app  # noqa: E402
from ytdl4k.gui.main_window import MainWindow  # noqa: E402
from ytdl4k.gui.model import PROGRESS, QueueModel, format_eta, format_speed  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    return build_app([])


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr("ytdl4k.gui.main_window.find_ffmpeg", lambda *a, **kw: None)
    settings = Settings(output_dir=tmp_path)
    queue = DownloadQueue(settings, ffmpeg=None, extractor=object(), downloader_factory=lambda task: None)
    win = MainWindow(settings, queue=queue)
    win.show()  # 자식 위젯의 표시 여부를 확인하려면 창이 떠 있어야 한다
    yield win
    win.queue.shutdown()
    win.close()


def add_fake(window, title: str, state: TaskState, percent: float = 0.0) -> DownloadTask:
    task = DownloadTask(url=f"https://youtu.be/{title}")
    task.state = state
    task.progress = Progress(stage=state, percent=percent)
    window.queue.tasks.append(task)
    window.model.task_added()
    return task


# ── 주소 입력 ────────────────────────────────────────────────────────────


def test_enter_adds_the_url(window):
    window.url_edit.setText("https://youtu.be/abc")
    window.add_current_url()
    assert [t.url for t in window.queue.tasks] == ["https://youtu.be/abc"]
    assert window.url_edit.text() == "", "추가한 뒤에는 입력칸이 비어야 한다"


def test_blank_input_does_nothing(window):
    window.url_edit.setText("   ")
    window.add_current_url()
    assert window.queue.tasks == []


def test_non_url_is_refused_with_guidance(window):
    window.add_url("설악산 단풍")
    assert window.queue.tasks == []
    assert window.detail_label.isVisible()
    assert "유튜브 영상 주소" in window.detail_label.text()


def test_clipboard_prefills_a_youtube_link(window):
    assert window.paste_from_clipboard("https://www.youtube.com/watch?v=abc123")
    assert window.url_edit.text() == "https://www.youtube.com/watch?v=abc123"
    assert window.queue.tasks == [], "붙여넣기만으로 받기 시작하면 안 된다"


def test_clipboard_ignores_other_text(window):
    assert not window.paste_from_clipboard("장 보기: 우유, 달걀")
    assert window.url_edit.text() == ""


def test_clipboard_does_not_overwrite_typing(window):
    window.url_edit.setText("https://youtu.be/입력중")
    assert not window.paste_from_clipboard("https://youtu.be/other")
    assert window.url_edit.text() == "https://youtu.be/입력중"


# ── 설정 ────────────────────────────────────────────────────────────────


def test_quality_choice_reaches_the_settings(window):
    window.quality_box.setCurrentIndex(window.quality_box.findData(1080))
    assert window.settings.max_height == 1080
    assert window.settings.target().max_height == 1080


def test_best_quality_means_no_limit(window):
    window.quality_box.setCurrentIndex(window.quality_box.findData(None))
    assert window.settings.max_height is None


def test_codec_and_audio_only_reach_the_settings(window):
    window.codec_box.setCurrentIndex(window.codec_box.findData(CodecPolicy.EFFICIENCY))
    window.audio_only.setChecked(True)
    assert window.settings.codec_policy is CodecPolicy.EFFICIENCY
    assert window.settings.target().audio_only is True


def test_choosing_a_browser_rebuilds_the_extractor(window):
    """쿠키 설정은 추출기를 새로 만들어야 실제로 적용된다."""
    before = window.queue.extractor
    window.cookie_box.setCurrentIndex(window.cookie_box.findData("firefox"))
    assert window.settings.cookies_from_browser == "firefox"
    assert window.queue.extractor is not before
    assert window.queue.extractor.base_options()["cookiesfrombrowser"][0] == "firefox"


def test_output_dir_change_is_shown_and_stored(window, tmp_path):
    target = tmp_path / "새 폴더"
    window.set_output_dir(target)
    assert window.settings.output_dir == target
    assert window.folder_label.toolTip() == str(target)


def test_settings_survive_a_restart(qt_app, tmp_path, monkeypatch):
    """창을 닫을 때 설정이 저장되고, 다음에 켤 때 그대로 돌아와야 한다."""
    monkeypatch.setattr("ytdl4k.gui.main_window.find_ffmpeg", lambda *a, **kw: None)
    monkeypatch.setattr("ytdl4k.app.settings.config_path", lambda: tmp_path / "config.toml")

    first = MainWindow(Settings(output_dir=tmp_path))
    first.quality_box.setCurrentIndex(first.quality_box.findData(720))
    first.codec_box.setCurrentIndex(first.codec_box.findData(CodecPolicy.EFFICIENCY.value))
    first.close()

    reopened = Settings.load(tmp_path / "config.toml")
    assert reopened.max_height == 720
    assert reopened.codec_policy is CodecPolicy.EFFICIENCY


# ── 목록 표시 ───────────────────────────────────────────────────────────


def test_status_summary_counts_states(window):
    add_fake(window, "a", TaskState.DOWNLOADING, 40)
    add_fake(window, "b", TaskState.DONE, 100)
    add_fake(window, "c", TaskState.FAILED)
    window._update_status()
    summary = window.summary_label.text()
    assert "받는 중 1" in summary and "완료 1" in summary and "실패 1" in summary


def test_progress_bar_only_where_it_means_something(window):
    downloading = add_fake(window, "a", TaskState.DOWNLOADING, 42)
    pending = add_fake(window, "b", TaskState.PENDING)
    model: QueueModel = window.model

    running_index = model.index(model.row_of(downloading), PROGRESS)
    waiting_index = model.index(model.row_of(pending), PROGRESS)

    assert model.data(running_index, Qt.UserRole) == 42
    assert model.data(running_index, Qt.DisplayRole) == "42%"
    assert model.data(waiting_index, Qt.UserRole) is None
    assert model.data(waiting_index, Qt.DisplayRole) == "—"


def test_failure_shows_cause_and_next_step(window):
    task = add_fake(window, "a", TaskState.FAILED)
    task.error = LoginRequired()
    window.table.selectRow(0)
    text = window.detail_label.text()
    assert "로그인이 필요한 영상입니다" in text
    assert "브라우저" in text, "무엇을 하면 되는지가 함께 보여야 한다"


def test_cancel_button_follows_the_selection(window):
    running = add_fake(window, "a", TaskState.DOWNLOADING, 10)
    add_fake(window, "b", TaskState.DONE, 100)

    window.table.selectRow(window.model.row_of(running))
    assert window.cancel_button.isEnabled()

    window.table.selectRow(1)
    assert not window.cancel_button.isEnabled(), "끝난 작업은 취소할 것이 없다"


def test_clear_finished_only_removes_finished(window):
    running = add_fake(window, "a", TaskState.DOWNLOADING, 10)
    add_fake(window, "b", TaskState.DONE, 100)
    window.clear_finished()
    assert [t.id for t in window.queue.tasks] == [running.id]
    assert window.model.rowCount() == 1


def test_open_button_needs_a_saved_file(window):
    task = add_fake(window, "a", TaskState.DONE, 100)
    window.table.selectRow(0)
    assert not window.open_button.isEnabled()

    task.output_path = Path("/tmp/영상.mkv")
    window._on_selection_changed()
    assert window.open_button.isEnabled()


def test_missing_ffmpeg_is_announced(window):
    assert "ffmpeg 없음" in window.statusBar().currentMessage()


# ── 표시 형식 ───────────────────────────────────────────────────────────


def test_speed_and_eta_are_readable():
    assert format_speed(11.4 * 2**20) == "11.4 MB/s"
    assert format_speed(900) == "1 KB/s"
    assert format_speed(None) == "—"
    assert format_eta(95) == "1분 35초 남음"
    assert format_eta(12) == "12초 남음"
    assert format_eta(None) == ""
