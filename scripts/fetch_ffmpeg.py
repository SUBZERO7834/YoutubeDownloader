#!/usr/bin/env python3
"""배포용 ffmpeg 바이너리를 ``ytdl4k/resources/ffmpeg/`` 에 채운다.

4K 는 영상과 음성이 분리되어 제공되므로 병합용 ffmpeg 이 없으면 제품이 성립하지 않는다.
사용자에게 "ffmpeg 을 먼저 설치하세요" 라고 떠넘기지 않기 위해 실행 파일에 함께 묶는다.

소스는 세 가지이고, 네트워크 환경에 따라 고를 수 있다::

    python scripts/fetch_ffmpeg.py                     # 공식 static 빌드 내려받기 (기본)
    python scripts/fetch_ffmpeg.py --from-pypi         # PyPI 만 열린 환경 (ffprobe 는 없음)
    python scripts/fetch_ffmpeg.py --from-path /usr/bin  # 이미 있는 바이너리 복사
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

DEST = Path(__file__).resolve().parent.parent / "ytdl4k" / "resources" / "ffmpeg"

# 각 플랫폼의 공식(에 준하는) static 빌드. ffmpeg 프로젝트가 직접 링크하는 배포처다.
DOWNLOADS: dict[str, list[str]] = {
    "linux": ["https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"],
    "windows": ["https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"],
    "darwin": [
        "https://evermeet.cx/ffmpeg/getrelease/zip",
        "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip",
    ],
}
WANTED = ("ffmpeg", "ffprobe")


def target_platform() -> str:
    system = platform.system().lower()
    return {"darwin": "darwin", "windows": "windows"}.get(system, "linux")


def exe_name(name: str, plat: str) -> str:
    return f"{name}.exe" if plat == "windows" else name


def from_path(source: Path, plat: str) -> list[Path]:
    copied = []
    for name in WANTED:
        candidate = source if source.is_file() else source / exe_name(name, plat)
        if candidate.is_file():
            copied.append(_install(candidate.read_bytes(), exe_name(name, plat)))
    return copied


def from_pypi(plat: str) -> list[Path]:
    """imageio-ffmpeg 휠에 들어 있는 static ffmpeg 을 쓴다.

    PyPI 외의 호스트가 막힌 환경(사내망, 샌드박스)에서 유일하게 동작하는 경로다.
    단 ffprobe 는 들어 있지 않다 — 결과 검증이 생략될 뿐, 병합 자체는 문제없다.
    """
    try:
        import imageio_ffmpeg
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "imageio-ffmpeg"], check=True)
        import imageio_ffmpeg

    source = Path(imageio_ffmpeg.get_ffmpeg_exe())
    return [_install(source.read_bytes(), exe_name("ffmpeg", plat))]


def from_web(plat: str) -> list[Path]:
    installed: list[Path] = []
    for url in DOWNLOADS[plat]:
        print(f"· 내려받는 중: {url}")
        with urllib.request.urlopen(url, timeout=180) as response:  # noqa: S310
            blob = response.read()
        installed += _extract(blob, url, plat)
    return installed


def _extract(blob: bytes, url: str, plat: str) -> list[Path]:
    wanted = {exe_name(n, plat) for n in WANTED}
    installed: list[Path] = []

    if url.endswith((".zip", "/zip")):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for member in archive.namelist():
                base = Path(member).name
                if base in wanted and not member.endswith("/"):
                    installed.append(_install(archive.read(member), base))
    else:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as archive:
            for member in archive.getmembers():
                base = Path(member.name).name
                if member.isfile() and base in wanted:
                    extracted = archive.extractfile(member)
                    if extracted:
                        installed.append(_install(extracted.read(), base))
    return installed


def _install(blob: bytes, name: str) -> Path:
    DEST.mkdir(parents=True, exist_ok=True)
    path = DEST / name
    path.write_bytes(blob)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def verify(path: Path) -> str:
    """받은 파일이 정말 실행되는지 확인한다. 크로스 플랫폼 수집이면 건너뛴다."""
    if path.suffix == ".exe" and os.name != "nt":
        return "(다른 플랫폼용 — 실행 확인 생략)"
    result = subprocess.run([str(path), "-version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"✗ 실행할 수 없습니다: {path}\n{result.stderr[:300]}")
    return result.stdout.splitlines()[0]


# 컨테이너별 먹싱/디먹싱 왕복. 병합이 실제로 거치는 경로를 그 컨테이너에
# 실제로 들어가는 코덱 조합으로 시험한다 (webm 에 mpeg4 를 넣는 식이면 오탐이 난다).
_ROUNDTRIPS = (
    ("mp4", "mp4", ("libx264", "aac"), "DASH 병합 (YouTube 4K)"),
    ("webm", "webm", ("libvpx", "libopus"), "VP9/Opus 병합"),
    ("matroska", "mkv", ("libx264", "libopus"), "혼합 코덱 병합"),
    ("mpegts", "ts", ("libx264", "aac"), "HLS·라이브 스트림"),
)
_MISSING_ENCODER = ("unknown encoder", "encoder not found", "cannot be used")


def health_check(ffmpeg: Path) -> list[str]:
    """ffmpeg 이 '실행된다' 를 넘어 '제 일을 한다' 까지 확인한다.

    ``-version`` 만 보고 넘어가면 특정 컨테이너에서 죽는 빌드를 배포하게 된다.
    실제로 PyPI 경유로 받은 static 빌드(7.0.2)는 MPEG-TS 입력에서 세그폴트했다 —
    먹싱은 멀쩡했기 때문에 왕복 검사가 아니면 드러나지 않는다.

    인코더가 없어 시험 파일을 못 만드는 경우는 실패로 치지 않는다. 병합은 어차피
    ``-c copy`` 라 인코더가 필요 없고, 여기서는 시험 입력을 만드는 데만 쓰인다.
    """
    if ffmpeg.suffix == ".exe" and os.name != "nt":
        return []

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for fmt, ext, (vcodec, acodec), purpose in _ROUNDTRIPS:
            sample = Path(tmp) / f"probe.{ext}"
            mux = subprocess.run(
                [
                    str(ffmpeg),
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=64x48:rate=10:duration=0.4",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=0.4",
                    "-c:v",
                    vcodec,
                    "-c:a",
                    acodec,
                    "-f",
                    fmt,
                    str(sample),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if mux.returncode != 0:
                if any(hint in mux.stderr.lower() for hint in _MISSING_ENCODER):
                    print(f"  - {ext}: {vcodec}/{acodec} 인코더가 없어 시험 생략")
                    continue
                problems.append(f"{ext}: 먹싱 실패 ({_why(mux.returncode)}) — {purpose}")
                continue
            demux = subprocess.run(
                [str(ffmpeg), "-v", "error", "-i", str(sample), "-f", "null", "-"],
                capture_output=True,
                text=True,
                check=False,
            )
            if demux.returncode != 0:
                problems.append(f"{ext}: 디먹싱 실패 ({_why(demux.returncode)}) — {purpose}")
    return problems


def _why(returncode: int) -> str:
    if returncode < 0:
        return f"시그널 {-returncode}{' (세그폴트)' if returncode == -11 else ''}"
    return f"종료코드 {returncode}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-path", metavar="DIR", help="이미 있는 ffmpeg/ffprobe 를 복사")
    source.add_argument("--from-pypi", action="store_true", help="PyPI 휠에서 가져오기 (ffprobe 없음)")
    parser.add_argument("--platform", choices=sorted(DOWNLOADS), default=target_platform())
    parser.add_argument("--skip-health-check", action="store_true", help="왕복 검사 생략")
    args = parser.parse_args(argv)

    plat = args.platform
    if args.from_path:
        installed = from_path(Path(args.from_path), plat)
    elif args.from_pypi:
        installed = from_pypi(plat)
    else:
        installed = from_web(plat)

    if not installed:
        raise SystemExit("✗ ffmpeg 을 가져오지 못했습니다.")

    for path in installed:
        print(f"✓ {path.name:<12} {path.stat().st_size / 2**20:6.1f}MB  {verify(path)}")
    if not (DEST / exe_name("ffprobe", plat)).exists():
        print("! ffprobe 가 없습니다 — 병합은 되지만 결과 트랙 검증은 생략됩니다.")

    ffmpeg = DEST / exe_name("ffmpeg", plat)
    if args.skip_health_check or not ffmpeg.exists():
        return 0

    print("· 컨테이너 왕복 검사…")
    problems = health_check(ffmpeg)
    if not problems:
        print("✓ mp4 / webm / mkv / ts 모두 먹싱·디먹싱 정상")
        return 0
    for problem in problems:
        print(f"✗ {problem}")
    fatal = any(p.startswith(("mp4", "webm", "mkv")) for p in problems)
    print(
        "\n이 빌드는 병합에 쓸 수 없습니다. 다른 소스로 다시 받으세요."
        if fatal
        else "\nDASH 병합(YouTube 4K)에는 문제가 없지만 위 형식은 처리하지 못합니다."
    )
    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(main())
