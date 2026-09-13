import threading
from pathlib import Path

import pytest

from ytdl4k.core.downloader import Downloader, _Canceled, _has_cause, glob_escape
from ytdl4k.core.errors import InsufficientDiskSpace
from ytdl4k.core.formats import select
from ytdl4k.core.merger import FfmpegTools
from ytdl4k.core.models import DownloadTarget, TaskState


@pytest.fixture
def downloader(tmp_path):
    return Downloader(output_dir=tmp_path, ffmpeg=FfmpegTools(Path("/usr/bin/ffmpeg"), None))


def test_build_options_merges_streams(downloader, info_4k):
    sel = select(info_4k, DownloadTarget())
    opts = downloader._build_options(sel, None)
    assert opts["format"] == "315+251"
    assert opts["merge_output_format"] == "webm"
    assert opts["continuedl"] is True  # 이어받기
    assert opts["ffmpeg_location"] == "/usr/bin"


def test_build_options_skips_merge_for_single_stream(downloader, info_4k):
    sel = select(info_4k, DownloadTarget(), can_merge=False)
    assert "merge_output_format" not in downloader._build_options(sel, None)


def test_progress_hook_reports_percent_and_speed(tmp_path, info_4k):
    seen = []
    dl = Downloader(output_dir=tmp_path, on_progress=seen.append)
    hook = dl._make_hook(None, TaskState.DOWNLOADING)
    hook(
        {
            "status": "downloading",
            "downloaded_bytes": 25,
            "total_bytes": 100,
            "speed": 1024.0,
            "eta": 9,
        }
    )
    assert seen[0].percent == 25.0
    assert seen[0].speed_bps == 1024.0
    assert seen[0].eta_s == 9


def test_progress_hook_ignores_other_statuses(tmp_path):
    seen = []
    dl = Downloader(output_dir=tmp_path, on_progress=seen.append)
    dl._make_hook(None, TaskState.DOWNLOADING)({"status": "finished"})
    assert seen == []


def test_cancel_event_interrupts_hook(tmp_path):
    dl = Downloader(output_dir=tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(_Canceled):
        dl._make_hook(cancel, TaskState.DOWNLOADING)({"status": "downloading"})


def test_merge_stage_is_reported(tmp_path):
    seen = []
    dl = Downloader(output_dir=tmp_path, on_progress=seen.append)
    dl._make_pp_hook(None)({"postprocessor": "Merger", "status": "started"})
    assert seen[0].stage is TaskState.MERGING


def test_check_space_raises_before_downloading(tmp_path, info_4k, monkeypatch):
    dl = Downloader(output_dir=tmp_path)
    sel = select(info_4k, DownloadTarget())  # 약 1.4GB
    monkeypatch.setattr("shutil.disk_usage", lambda p: type("U", (), {"free": 100 * 2**20})())
    with pytest.raises(InsufficientDiskSpace) as err:
        dl.check_space(sel, info_4k.duration)
    assert "남은 공간" in err.value.full_message


def test_check_space_passes_when_room_available(tmp_path, info_4k, monkeypatch):
    dl = Downloader(output_dir=tmp_path)
    sel = select(info_4k, DownloadTarget())
    monkeypatch.setattr("shutil.disk_usage", lambda p: type("U", (), {"free": 100 * 2**30})())
    dl.check_space(sel, info_4k.duration)  # 예외 없음


def test_resolve_path_prefers_requested_downloads(tmp_path):
    result = {"requested_downloads": [{"filepath": str(tmp_path / "out.mkv")}]}
    assert Downloader._resolve_path(None, result) == tmp_path / "out.mkv"


def test_resolve_path_falls_back_to_extension_glob(tmp_path):
    """병합 후 확장자가 바뀌므로 템플릿 추측만으로는 못 찾는다."""
    actual = tmp_path / "제목 [abc].mkv"
    actual.write_bytes(b"x")

    class FakeYdl:
        def prepare_filename(self, result):
            return str(tmp_path / "제목 [abc].webm")

    assert Downloader._resolve_path(FakeYdl(), {"id": "abc"}) == actual


def test_glob_escape_protects_bracketed_titles():
    assert glob_escape("제목 [abc]") == "제목 [[]abc]"


def test_has_cause_walks_the_chain():
    try:
        try:
            raise _Canceled()
        except _Canceled as inner:
            raise RuntimeError("wrapped") from inner
    except RuntimeError as outer:
        assert _has_cause(outer, _Canceled)
    assert not _has_cause(RuntimeError("plain"), _Canceled)
