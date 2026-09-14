import subprocess
from pathlib import Path

import pytest

from ytdl4k.cli.main import _bar, _hms, _ProgressReporter, main, parse_quality
from ytdl4k.core.downloader import Progress
from ytdl4k.core.errors import LoginRequired
from ytdl4k.core.merger import FfmpegTools
from ytdl4k.core.models import TaskState


@pytest.mark.parametrize(
    ("text", "expected"),
    [("2160", 2160), ("1080p", 1080), ("best", None), ("MAX", None), ("최고", None)],
)
def test_parse_quality(text, expected):
    assert parse_quality(text) == expected


def test_parse_quality_rejects_garbage():
    with pytest.raises(SystemExit):
        parse_quality("아주좋게")


def test_hms():
    assert _hms(59) == "0:59"
    assert _hms(605) == "10:05"
    assert _hms(3661) == "1:01:01"


def test_bar_endpoints():
    assert _bar(0).count("#") == 0
    assert _bar(100).count(".") == 0
    assert _bar(150).count("#") == _bar(100).count("#")  # 100% 를 넘어도 깨지지 않는다


def test_progress_reporter_throttles(capsys):
    """첫 이벤트는 기기 가동 시간과 무관하게 항상 나가야 한다."""
    reporter = _ProgressReporter(interval=60)
    reporter(Progress(stage=TaskState.DOWNLOADING, percent=1.0))
    reporter(Progress(stage=TaskState.DOWNLOADING, percent=2.0))  # 억제됨
    reporter(Progress(stage=TaskState.DOWNLOADING, percent=100.0))  # 완료는 항상 출력
    err = capsys.readouterr().err
    assert "1.0%" in err and "2.0%" not in err and "100.0%" in err


@pytest.fixture
def fake_cli(monkeypatch, info_4k):
    class FakeExtractor:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def base_options(self):
            return {}

        def extract(self, url):
            return info_4k

    monkeypatch.setattr("ytdl4k.cli.main.YtDlpExtractor", FakeExtractor)
    monkeypatch.setattr(
        "ytdl4k.cli.main.find_ffmpeg", lambda loc=None: FfmpegTools(Path("/usr/bin/ffmpeg"), None)
    )
    return FakeExtractor


def test_dry_run_reports_selection(fake_cli, capsys):
    assert main(["--dry-run", "https://youtu.be/x"]) == 0
    out = capsys.readouterr().out
    assert "2160p60 vp9 + opus" in out and ".webm" in out


def test_dry_run_honours_quality_flag(fake_cli, capsys):
    assert main(["--dry-run", "-q", "1080", "https://youtu.be/x"]) == 0
    assert "1080p60" in capsys.readouterr().out


def test_list_formats(fake_cli, capsys):
    assert main(["-F", "https://youtu.be/x"]) == 0
    out = capsys.readouterr().out
    assert "4320p" in out and "2160p" in out and "오디오" in out


def test_downgrade_is_announced(fake_cli, capsys):
    main(["--dry-run", "-q", "2000", "https://youtu.be/x"])
    assert "1440p 로 받습니다" in capsys.readouterr().err


def test_no_urls_prints_help(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().out


def test_app_error_is_reported_with_hint(monkeypatch, capsys):
    class FailingExtractor:
        def __init__(self, **kwargs):
            pass

        def base_options(self):
            return {}

        def extract(self, url):
            raise LoginRequired()

    monkeypatch.setattr("ytdl4k.cli.main.YtDlpExtractor", FailingExtractor)
    assert main(["https://youtu.be/x"]) == 1
    err = capsys.readouterr().err
    assert "로그인이 필요한 영상입니다" in err
    assert "--cookies-from-browser" in err  # 다음에 뭘 하면 되는지까지


def test_warns_when_ffmpeg_missing(monkeypatch, capsys, info_4k):
    class FakeExtractor:
        def __init__(self, **kwargs):
            pass

        def base_options(self):
            return {}

        def extract(self, url):
            return info_4k

    monkeypatch.setattr("ytdl4k.cli.main.YtDlpExtractor", FakeExtractor)
    monkeypatch.setattr("ytdl4k.cli.main.find_ffmpeg", lambda loc=None: None)
    assert main(["--dry-run", "https://youtu.be/x"]) == 0
    captured = capsys.readouterr()
    assert "ffmpeg" in captured.err
    assert "360p" in captured.out  # 병합이 불가능하면 progressive 로 내려간다


def test_self_check_reports_components(monkeypatch, capsys, tmp_path):
    from ytdl4k.cli.main import self_check

    exe = tmp_path / "ffmpeg"
    exe.write_text("")
    monkeypatch.setattr("ytdl4k.cli.main.find_ffmpeg", lambda loc=None: FfmpegTools(exe, None))
    # 실제로 실행하면 플랫폼마다 결과가 다르다(윈도우는 셸 스크립트를 못 띄운다).
    monkeypatch.setattr(
        "ytdl4k.cli.main.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, "ffmpeg version 7.0.2-static\n", ""),
    )
    assert self_check() == 0
    out = capsys.readouterr().out
    assert "ytdl4k" in out and "yt-dlp" in out and str(exe) in out
    assert "7.0.2-static" in out  # ffmpeg 을 실제로 실행해 버전을 읽는다


def test_self_check_fails_without_ffmpeg(monkeypatch, capsys):
    from ytdl4k.cli.main import self_check

    monkeypatch.setattr("ytdl4k.cli.main.find_ffmpeg", lambda loc=None: None)
    assert self_check() == 1
    assert "찾지 못함" in capsys.readouterr().out


def test_broken_pipe_is_swallowed(monkeypatch):
    """`ytdl4k -F URL | head` 로 파이프가 끊겨도 트레이스백을 뱉지 않는다.

    실제 ``os.dup2`` 는 pytest 의 출력 캡처 fd 를 덮어써 버리므로 가로챈다.
    """
    import ytdl4k.cli.main as cli

    redirected = []
    monkeypatch.setattr(cli, "_run", lambda args: (_ for _ in ()).throw(BrokenPipeError()))
    monkeypatch.setattr(cli.os, "dup2", lambda *a: redirected.append(a))
    assert main(["-F", "https://youtu.be/x"]) == 0
    assert redirected, "남은 출력을 /dev/null 로 돌리지 않았습니다"


def test_first_progress_event_survives_low_monotonic_clock(capsys, monkeypatch):
    """갓 부팅한 기기(= time.monotonic() 이 작음)에서도 첫 진행률은 나가야 한다.

    스로틀 기준값을 0 으로 두면 `now - 0 < interval` 이 참이 되어 첫 이벤트가 묻혔다.
    CI 러너에서만 재현되던 실패다.
    """
    monkeypatch.setattr("time.monotonic", lambda: 0.5)
    reporter = _ProgressReporter(interval=60)
    reporter(Progress(stage=TaskState.DOWNLOADING, percent=1.0))
    assert "1.0%" in capsys.readouterr().err


def test_output_survives_a_non_utf8_stream():
    """윈도우 CI 재현: 리다이렉트된 출력이 cp1252 면 한글·✓ 에서 죽었다."""
    import io

    from ytdl4k.console import configure_output

    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    with pytest.raises(UnicodeEncodeError):
        stream.write("✓ 저장 완료")
        stream.flush()

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    configure_output(stream)
    stream.write("✓ 저장 완료")          # 더 이상 죽지 않는다
    stream.flush()
