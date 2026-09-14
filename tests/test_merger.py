import sys
from pathlib import Path

from ytdl4k.core.merger import FfmpegTools, find_ffmpeg, verify_output

EXE = ".exe" if sys.platform == "win32" else ""  # 윈도우는 확장자가 있어야 실행 파일이다


def test_find_ffmpeg_accepts_explicit_file(tmp_path):
    exe = tmp_path / f"ffmpeg{EXE}"
    exe.write_text("#!/bin/sh\n")
    tools = find_ffmpeg(exe)
    assert tools is not None and tools.ffmpeg == exe
    assert tools.location == str(tmp_path)


def test_find_ffmpeg_accepts_directory_and_finds_ffprobe(tmp_path):
    (tmp_path / f"ffmpeg{EXE}").write_text("")
    (tmp_path / f"ffprobe{EXE}").write_text("")
    tools = find_ffmpeg(tmp_path)
    assert tools.ffprobe == tmp_path / f"ffprobe{EXE}"


def test_find_ffmpeg_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("ytdl4k.core.merger._BUNDLE_DIR", tmp_path / "nope")
    assert find_ffmpeg() is None


def test_verify_output_flags_empty_file(tmp_path):
    missing = tmp_path / "out.mkv"
    tools = FfmpegTools(Path("/usr/bin/ffmpeg"), None)
    assert verify_output(missing, tools, expect_video=True, expect_audio=True)


def test_verify_output_skips_when_no_ffprobe(tmp_path):
    out = tmp_path / "out.mkv"
    out.write_bytes(b"data")
    tools = FfmpegTools(Path("/usr/bin/ffmpeg"), None)
    assert verify_output(out, tools, expect_video=True, expect_audio=True) == []


def test_verify_output_detects_missing_audio_track(tmp_path, monkeypatch):
    out = tmp_path / "out.mkv"
    out.write_bytes(b"data")
    tools = FfmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"))
    monkeypatch.setattr("ytdl4k.core.merger.probe_streams", lambda path, tools: [{"codec_type": "video"}])
    problems = verify_output(out, tools, expect_video=True, expect_audio=True)
    assert problems and "음성 트랙이 없습니다" in problems[0]


def test_bundle_dir_follows_pyinstaller_unpack_root(monkeypatch, tmp_path):
    """PyInstaller 로 묶이면 리소스는 _MEIPASS 아래에 풀린다."""
    from ytdl4k.core import merger

    monkeypatch.setattr(merger.sys, "frozen", True, raising=False)
    monkeypatch.setattr(merger.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert merger._bundle_dir() == tmp_path / "resources" / "ffmpeg"


def test_bundle_dir_uses_source_tree_when_not_frozen(monkeypatch):
    from ytdl4k.core import merger

    monkeypatch.delattr(merger.sys, "frozen", raising=False)
    assert merger._bundle_dir().parts[-3:] == ("ytdl4k", "resources", "ffmpeg")
