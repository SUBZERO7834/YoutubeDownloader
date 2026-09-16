"""명령줄 인터페이스.

사용 예::

    ytdl4k https://youtu.be/XXXX              # 4K 이하 최고 화질
    ytdl4k -q 1080 -o ~/Videos URL            # 1080p, 저장 위치 지정
    ytdl4k -F URL                             # 받을 수 있는 화질 목록만 보기
    ytdl4k --audio-only URL                   # 오디오만
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from .. import __version__
from ..console import configure_output
from ..core.downloader import DEFAULT_TEMPLATE, Downloader, Progress, embed_blocker
from ..core.errors import AppError
from ..core.extractor import YtDlpExtractor
from ..core.formats import list_downloadable, select
from ..core.merger import find_ffmpeg
from ..core.models import (
    CodecPolicy,
    Container,
    DownloadTarget,
    TaskState,
    ThumbnailMode,
    VideoInfo,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ytdl4k",
        description="YouTube 동영상을 최대 4K 화질로 내려받습니다.",
    )
    p.add_argument("urls", nargs="*", help="YouTube 영상 URL (여러 개 가능)")
    p.add_argument(
        "-q",
        "--quality",
        default="2160",
        help="목표 화질: best 또는 2160/1440/1080/720 (기본: 2160)",
    )
    p.add_argument("-o", "--output", default=".", help="저장 폴더 (기본: 현재 폴더)")
    p.add_argument("-F", "--list-formats", action="store_true", help="화질 목록만 출력")
    p.add_argument(
        "--codec",
        choices=[c.value for c in CodecPolicy],
        default=CodecPolicy.QUALITY.value,
        help="코덱 선호: quality=VP9, efficiency=AV1(용량↓), compatibility=H.264",
    )
    p.add_argument(
        "--container",
        choices=[c.value for c in Container],
        default=Container.AUTO.value,
        help="컨테이너 강제 (기본: auto — 무손실로 담기는 것을 자동 선택)",
    )
    p.add_argument("--audio-only", action="store_true", help="오디오만 받기")
    p.add_argument("--hdr", action="store_true", help="HDR 스트림이 있으면 우선 선택")
    p.add_argument(
        "--thumbnail",
        choices=[m.value for m in ThumbnailMode],
        default=ThumbnailMode.NONE.value,
        help="썸네일: none=안 함, file=그림 파일로 저장, embed=영상 안에 표지로 넣기",
    )
    p.add_argument("--template", default=DEFAULT_TEMPLATE, help="파일명 템플릿")
    p.add_argument("--overwrite", action="store_true", help="같은 파일이 있으면 덮어쓰기")
    p.add_argument(
        "-j",
        "--concurrent-fragments",
        type=int,
        default=4,
        help="조각 동시 다운로드 수 (기본: 4)",
    )
    p.add_argument("--cookies-from-browser", help="예: chrome, firefox, edge (연령 제한 영상 등)")
    p.add_argument("--cookies", help="쿠키 파일 경로")
    p.add_argument("--ffmpeg-location", help="ffmpeg 실행 파일 또는 폴더 경로")
    p.add_argument("--dry-run", action="store_true", help="선택 결과만 보고 받지 않기")
    p.add_argument(
        "--self-check", action="store_true", help="구성 진단: yt-dlp·ffmpeg 이 제대로 잡히는지 확인"
    )
    p.add_argument("--gui", action="store_true", help="창 화면으로 실행")
    p.add_argument("--version", action="version", version=f"ytdl4k {__version__}")
    return p


def say(text: str = "") -> None:
    """정보 출력.

    진행률은 stderr 를 ``\r`` 로 덮어쓰며 갱신된다. stdout 이 버퍼링되면
    두 흐름의 순서가 뒤엉키므로(파이프로 넘길 때 특히) 매번 flush 한다.
    """
    print(text, flush=True)


def parse_quality(value: str) -> int | None:
    if value.lower() in ("best", "max", "최고"):
        return None
    digits = value.lower().rstrip("p")
    if not digits.isdigit():
        raise SystemExit(f"화질 값을 이해하지 못했습니다: {value} (예: best, 2160, 1080)")
    return int(digits)


def launch_gui() -> int:
    """창 화면을 띄운다. PySide6 는 CLI 전용 설치에는 없을 수 있다."""
    try:
        from ..gui import run
    except ImportError as exc:
        # 실행 파일을 받아 쓰는 사람에게 pip 명령을 알려 줘 봐야 소용이 없다.
        remedy = (
            "창 화면판(ytdl4k-gui)을 따로 내려받아 실행해 주세요."
            if getattr(sys, "frozen", False)
            else 'pip install "ytdl4k[gui]" 로 설치할 수 있습니다.'
        )
        print(f"이 실행 파일에는 창 화면이 들어 있지 않습니다.\n{remedy}", file=sys.stderr)
        print(f"(원본 오류: {exc})", file=sys.stderr)
        return 1
    return run()


def _thumbnail_support(tools) -> str:
    """어떤 컨테이너에 표지를 넣을 수 있는지 한 줄로."""
    ok = [c for c in ("mp4", "m4a", "mkv") if not embed_blocker(c, tools)]
    if not ok:
        return "불가 — 그림 파일로만 저장됩니다"
    blocked = [c for c in ("mp4", "m4a", "mkv") if embed_blocker(c, tools)]
    text = ", ".join(f".{c}" for c in ok) + " 가능"
    return text + (f" (.{'/.'.join(blocked)} 불가)" if blocked else "")


def self_check(ffmpeg_location: str | None = None) -> int:
    """구성 진단.

    실행 파일로 묶고 나면 '왜 4K 가 안 되지' 의 원인은 대개 둘 중 하나다 —
    yt-dlp 가 안 딸려 왔거나, ffmpeg 을 못 찾거나. 그 둘을 바로 보여 준다.
    """
    say(f"ytdl4k        {__version__}")
    say(f"Python        {sys.version.split()[0]}")
    say(f"실행 형태     {'단일 실행 파일 (PyInstaller)' if getattr(sys, 'frozen', False) else '소스'}")

    try:
        import yt_dlp

        say(f"yt-dlp        {yt_dlp.version.__version__}")
    except ImportError as exc:
        say(f"yt-dlp        ✗ 불러오지 못했습니다 ({exc})")
        return 1

    tools = find_ffmpeg(ffmpeg_location)
    if tools is None:
        say("ffmpeg        ✗ 찾지 못함 — 1080p 초과 화질을 받을 수 없습니다")
        return 1

    version = subprocess.run([str(tools.ffmpeg), "-version"], capture_output=True, text=True, check=False)
    first_line = version.stdout.splitlines()[0] if version.stdout else "(버전 확인 실패)"
    say(f"ffmpeg        {tools.ffmpeg}")
    say(f"              {first_line}")
    say(f"ffprobe       {tools.ffprobe or '없음 — 결과 트랙 검증과 mkv 표지 넣기를 건너뜁니다'}")
    say(f"썸네일 넣기   {_thumbnail_support(tools)}")
    say("\n4K 다운로드에 필요한 구성이 모두 준비됐습니다.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_output()
    try:
        return _run(build_parser().parse_args(argv))
    except BrokenPipeError:
        # `ytdl4k -F URL | head` 처럼 받는 쪽이 먼저 닫은 경우다.
        # 남은 출력을 버려 종료 시점에 트레이스백이 다시 뜨는 것을 막는다.
        # stdout 이 파일 디스크립터가 없는 객체(테스트 캡처 등)일 수도 있다.
        with contextlib.suppress(OSError, ValueError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


def _run(args: argparse.Namespace) -> int:
    if args.gui:
        return launch_gui()
    if args.self_check:
        return self_check(args.ffmpeg_location)
    if not args.urls:
        build_parser().print_help()
        return 2

    target = DownloadTarget(
        max_height=parse_quality(args.quality),
        codec_policy=CodecPolicy(args.codec),
        container=Container(args.container),
        audio_only=args.audio_only,
        prefer_hdr=args.hdr,
        thumbnail=ThumbnailMode(args.thumbnail),
    )
    ffmpeg = find_ffmpeg(args.ffmpeg_location)
    if ffmpeg is None:
        print(
            "! ffmpeg 을 찾지 못했습니다. 1080p 를 넘는 화질은 영상과 음성이 분리되어 있어\n"
            "  병합에 ffmpeg 이 필요합니다. 지금은 영상+음성이 한 파일인 포맷만 받습니다.",
            file=sys.stderr,
        )

    extractor = YtDlpExtractor(cookies_from_browser=args.cookies_from_browser, cookie_file=args.cookies)

    failures = 0
    for url in args.urls:
        try:
            failures += _handle_url(url, args, target, extractor, ffmpeg)
        except AppError as err:
            print(f"\n✗ {url}\n  {err.full_message}", file=sys.stderr)
            failures += 1
        except KeyboardInterrupt:
            print("\n중단했습니다.", file=sys.stderr)
            return 130
    return 1 if failures else 0


def _handle_url(url, args, target, extractor, ffmpeg) -> int:
    print(f"· 정보를 읽는 중… {url}", file=sys.stderr)
    info = extractor.extract(url)
    say(f"  {info.title}" + (f"  ({_hms(info.duration)})" if info.duration else ""))

    if args.list_formats:
        _print_formats(info)
        return 0

    selection = select(info, target, can_merge=ffmpeg is not None)
    size = selection.estimated_size(info.duration)
    size_text = f"  약 {size / 2**20:.0f}MB" if size else ""
    say(f"  선택: {selection.describe()}{size_text}")

    if target.max_height and selection.height and selection.height < target.max_height:
        print(f"  ! {target.max_height}p 가 없어 {selection.height}p 로 받습니다.", file=sys.stderr)
    if args.dry_run:
        return 0

    reporter = _ProgressReporter()
    downloader = Downloader(
        output_dir=Path(args.output).expanduser(),
        base_options=extractor.base_options(),
        filename_template=args.template,
        ffmpeg=ffmpeg,
        concurrent_fragments=args.concurrent_fragments,
        overwrite=args.overwrite,
        thumbnail=target.thumbnail,
        on_progress=reporter,
    )
    if target.thumbnail is ThumbnailMode.EMBED:
        blocker = embed_blocker(selection.container, ffmpeg)
        if blocker:
            print(f"  ! {blocker}. 그림 파일로 따로 저장합니다.", file=sys.stderr)
    downloader.check_space(selection, info.duration)

    cancel = threading.Event()
    with _sigint_to(cancel):
        path = downloader.download(info, selection, cancel_event=cancel)
    reporter.finish()
    say(f"✓ 저장 완료: {path}")
    return 0


def _print_formats(info: VideoInfo) -> None:
    say(f"\n  {'화질':<16} {'코덱':<8} {'ID':<8} {'용량':>10}")
    say(f"  {'-' * 46}")
    for f in list_downloadable(info):
        size = f.estimated_size(info.duration)
        size_text = f"{size / 2**20:.0f}MB" if size else "-"
        kind = "" if f.is_combined else " (음성 별도)"
        say(
            f"  {(f.describe().split()[0] + kind):<16} {f.video_codec or '-':<8} "
            f"{f.format_id:<8} {size_text:>10}"
        )
    audios = sorted(info.audio_formats, key=lambda f: f.tbr or 0, reverse=True)
    if audios:
        say("\n  오디오: " + ", ".join(f"{a.describe()} ({a.format_id})" for a in audios[:4]))


class _ProgressReporter:
    """진행률을 stderr 한 줄에 갱신한다. 200ms 로 제한해 과도한 출력을 막는다."""

    def __init__(self, interval: float = 0.2) -> None:
        self.interval = interval
        # 0 으로 두면 갓 부팅한 기기에서 time.monotonic() 이 작아 첫 이벤트가 묻힌다.
        self._last = -math.inf
        self._active = False

    def __call__(self, progress: Progress) -> None:
        if progress.stage is TaskState.MERGING:
            self._write("  병합 중…")
            return
        if progress.stage is not TaskState.DOWNLOADING:
            return
        now = time.monotonic()
        if now - self._last < self.interval and progress.percent < 100:
            return
        self._last = now
        speed = f"{progress.speed_bps / 2**20:.1f}MB/s" if progress.speed_bps else "--"
        eta = f"{progress.eta_s}s" if progress.eta_s else "--"
        total = f"{progress.total_bytes / 2**20:.0f}MB" if progress.total_bytes else "?"
        self._write(f"  {_bar(progress.percent)} {progress.percent:5.1f}%  {total}  {speed}  ETA {eta}")

    def _write(self, text: str) -> None:
        sys.stderr.write("\r\033[K" + text)
        sys.stderr.flush()
        self._active = True

    def finish(self) -> None:
        if self._active:
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()
            self._active = False


def _bar(percent: float, width: int = 24) -> str:
    filled = int(width * max(0.0, min(100.0, percent)) / 100)
    return "[" + "#" * filled + "." * (width - filled) + "]"


def _hms(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class _sigint_to:
    """첫 Ctrl+C 는 '이어받기 가능한 취소', 두 번째는 즉시 중단."""

    def __init__(self, event: threading.Event) -> None:
        self.event = event
        self.previous = None

    def __enter__(self):
        def handler(signum, frame):
            if self.event.is_set() and callable(self.previous):
                self.previous(signum, frame)
                return
            self.event.set()
            print("\n중단 요청 — 받던 조각을 정리하는 중입니다…", file=sys.stderr)

        try:
            self.previous = signal.signal(signal.SIGINT, handler)
        except ValueError:  # 메인 스레드가 아니면 핸들러를 못 건다
            self.previous = None
        return self

    def __exit__(self, *exc):
        if self.previous is not None:
            signal.signal(signal.SIGINT, self.previous)
        return False
