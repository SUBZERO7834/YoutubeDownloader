"""배포용 ffmpeg 확보 스크립트 검증.

이 스크립트가 잘못 동작하면 '실행은 되는데 병합에서 죽는' 실행 파일이 배포된다.
네트워크를 타지 않는 부분(경로 선택·복사·판정)만 검증한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_ffmpeg  # noqa: E402


@pytest.fixture(autouse=True)
def dest(tmp_path, monkeypatch):
    """진짜 리소스 폴더를 건드리지 않도록 목적지를 임시 폴더로 돌린다."""
    target = tmp_path / "resources"
    monkeypatch.setattr(fetch_ffmpeg, "DEST", target)
    return target


def test_exe_name_is_platform_specific():
    assert fetch_ffmpeg.exe_name("ffmpeg", "windows") == "ffmpeg.exe"
    assert fetch_ffmpeg.exe_name("ffmpeg", "linux") == "ffmpeg"
    assert fetch_ffmpeg.exe_name("ffprobe", "darwin") == "ffprobe"


def test_from_path_copies_both_binaries(tmp_path, dest):
    source = tmp_path / "src"
    source.mkdir()
    (source / "ffmpeg").write_bytes(b"MZ-ffmpeg")
    (source / "ffprobe").write_bytes(b"MZ-ffprobe")

    copied = fetch_ffmpeg.from_path(source, "linux")

    assert {p.name for p in copied} == {"ffmpeg", "ffprobe"}
    assert (dest / "ffmpeg").read_bytes() == b"MZ-ffmpeg"


def test_from_path_tolerates_missing_ffprobe(tmp_path, dest):
    source = tmp_path / "src"
    source.mkdir()
    (source / "ffmpeg").write_bytes(b"x")

    copied = fetch_ffmpeg.from_path(source, "linux")

    assert [p.name for p in copied] == ["ffmpeg"]


@pytest.mark.skipif(sys.platform == "win32", reason="윈도우는 확장자로 실행 여부를 판단한다")
def test_installed_binary_is_executable(dest):
    path = fetch_ffmpeg._install(b"payload", "ffmpeg")
    assert path.stat().st_mode & 0o111, "실행 권한이 없으면 병합 단계에서 실패한다"


def test_installed_binary_keeps_its_bytes(dest):
    path = fetch_ffmpeg._install(b"payload", "ffmpeg")
    assert path.read_bytes() == b"payload"


def test_why_names_the_signal():
    assert "세그폴트" in fetch_ffmpeg._why(-11)
    assert "시그널 9" in fetch_ffmpeg._why(-9)
    assert fetch_ffmpeg._why(1) == "종료코드 1"


def test_health_check_skips_foreign_platform_binary(tmp_path):
    """윈도우용 바이너리를 리눅스에서 실행해 보는 것은 의미가 없다."""
    if sys.platform == "win32":
        pytest.skip("윈도우에서는 .exe 가 실행 가능하다")
    assert fetch_ffmpeg.health_check(tmp_path / "ffmpeg.exe") == []
