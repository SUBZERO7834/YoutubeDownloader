"""ffmpeg 연동.

실제 병합(remux)은 yt-dlp 가 ffmpeg 을 호출해 수행한다 — 이미 검증된 경로를
다시 구현할 이유가 없다. 이 모듈이 맡는 일은 세 가지다.

1. 번들 → PATH 순서로 ffmpeg 을 **찾는다**
2. 결과 파일에 영상·음성 트랙이 실제로 들어갔는지 **검증한다**
3. (선택) 컨테이너만 바꾸는 remux 를 직접 실행한다
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import FfmpegNotFound


def _bundle_dir() -> Path:
    """번들된 ffmpeg 이 있는 폴더.

    PyInstaller 로 묶이면 리소스는 소스 트리가 아니라 실행 시 풀리는
    임시 폴더(``sys._MEIPASS``) 아래에 놓인다. 이 차이를 여기서 흡수한다.
    """
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        return root / "resources" / "ffmpeg"
    return Path(__file__).resolve().parent.parent / "resources" / "ffmpeg"


_BUNDLE_DIR = _bundle_dir()


@dataclass(frozen=True)
class FfmpegTools:
    ffmpeg: Path
    ffprobe: Path | None

    @property
    def location(self) -> str:
        """yt-dlp 의 ``ffmpeg_location`` 에 넘길 디렉터리 경로."""
        return str(self.ffmpeg.parent)


def find_ffmpeg(explicit: str | Path | None = None) -> FfmpegTools | None:
    """ffmpeg 을 찾는다. 없으면 None (호출 측이 degrade 를 결정한다)."""
    for base in (explicit, _BUNDLE_DIR):
        if not base:
            continue
        path = Path(base)
        cand = path if path.is_file() else path / _exe("ffmpeg")
        if cand.is_file():
            probe = cand.parent / _exe("ffprobe")
            return FfmpegTools(cand, probe if probe.is_file() else None)

    found = shutil.which("ffmpeg")
    if found:
        probe = shutil.which("ffprobe")
        return FfmpegTools(Path(found), Path(probe) if probe else None)
    return None


def require_ffmpeg(explicit: str | Path | None = None) -> FfmpegTools:
    tools = find_ffmpeg(explicit)
    if tools is None:
        raise FfmpegNotFound()
    return tools


def _exe(name: str) -> str:
    return f"{name}.exe" if sys.platform == "win32" else name


def probe_streams(path: Path, tools: FfmpegTools) -> list[dict]:
    """ffprobe 로 트랙 목록을 읽는다. ffprobe 가 없으면 빈 리스트."""
    if tools.ffprobe is None:
        return []
    result = subprocess.run(
        [
            str(tools.ffprobe),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout).get("streams", [])
    except json.JSONDecodeError:
        return []


def verify_output(path: Path, tools: FfmpegTools, *, expect_video: bool, expect_audio: bool) -> list[str]:
    """결과 파일 검증. 문제를 문자열 목록으로 돌려준다 (비어 있으면 정상).

    병합이 조용히 실패해 '영상만 있고 소리가 없는 4K 파일' 이 나오는 사고를
    막기 위한 마지막 관문이다.
    """
    problems: list[str] = []
    if not path.exists() or path.stat().st_size == 0:
        return [f"결과 파일이 비어 있습니다: {path}"]

    streams = probe_streams(path, tools)
    if not streams:
        return problems  # ffprobe 가 없으면 검증을 건너뛴다 (실패로 취급하지 않는다)

    kinds = [s.get("codec_type") for s in streams]
    if expect_video and "video" not in kinds:
        problems.append("영상 트랙이 없습니다.")
    if expect_audio and "audio" not in kinds:
        problems.append("음성 트랙이 없습니다. 병합이 제대로 되지 않았습니다.")
    return problems


def remux(src: Path, dst: Path, tools: FfmpegTools) -> None:
    """재인코딩 없이 컨테이너만 바꾼다."""
    cmd = [str(tools.ffmpeg), "-y", "-i", str(src), "-c", "copy", str(dst)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"remux 실패: {result.stderr[-500:]}")
