"""명령줄 인터페이스.

사용 예::

    ytdl4k https://youtu.be/XXXX              # 4K 이하 최고 화질
    ytdl4k -q 1080 -o ~/Videos URL            # 1080p, 저장 위치 지정
    ytdl4k -F URL                             # 받을 수 있는 화질 목록만 보기
    ytdl4k --audio-only URL                   # 오디오만
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from .. import __version__
from ..core.downloader import DEFAULT_TEMPLATE, Downloader, Progress
from ..core.errors import AppError
from ..core.extractor import YtDlpExtractor
from ..core.formats import list_downloadable, select
from ..core.merger import find_ffmpeg
from ..core.models import CodecPolicy, Container, DownloadTarget, TaskState, VideoInfo


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
    p.add_argument("--version", action="version", version=f"ytdl4k {__version__}")
    return p


def parse_quality(value: str) -> int | None:
    if value.lower() in ("best", "max", "최고"):
        return None
    digits = value.lower().rstrip("p")
    if not digits.isdigit():
        raise SystemExit(f"화질 값을 이해하지 못했습니다: {value} (예: best, 2160, 1080)")
    return int(digits)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.urls:
        build_parser().print_help()
        return 2

    target = DownloadTarget(
        max_height=parse_quality(args.quality),
        codec_policy=CodecPolicy(args.codec),
        container=Container(args.container),
        audio_only=args.audio_only,
        prefer_hdr=args.hdr,
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
    print(f"  {info.title}" + (f"  ({_hms(info.duration)})" if info.duration else ""))

    if args.list_formats:
        _print_formats(info)
        return 0

    selection = select(info, target, can_merge=ffmpeg is not None)
    size = selection.estimated_size(info.duration)
    size_text = f"  약 {size / 2**20:.0f}MB" if size else ""
    print(f"  선택: {selection.describe()}{size_text}")

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
        on_progress=reporter,
    )
    downloader.check_space(selection, info.duration)

    cancel = threading.Event()
    with _sigint_to(cancel):
        path = downloader.download(info, selection, cancel_event=cancel)
    reporter.finish()
    print(f"✓ 저장 완료: {path}")
    return 0


def _print_formats(info: VideoInfo) -> None:
    print(f"\n  {'화질':<16} {'코덱':<8} {'ID':<8} {'용량':>10}")
    print(f"  {'-' * 46}")
    for f in list_downloadable(info):
        size = f.estimated_size(info.duration)
        size_text = f"{size / 2**20:.0f}MB" if size else "-"
        kind = "" if f.is_combined else " (음성 별도)"
        print(
            f"  {(f.describe().split()[0] + kind):<16} {f.video_codec or '-':<8} "
            f"{f.format_id:<8} {size_text:>10}"
        )
    audios = sorted(info.audio_formats, key=lambda f: f.tbr or 0, reverse=True)
    if audios:
        print("\n  오디오: " + ", ".join(f"{a.describe()} ({a.format_id})" for a in audios[:4]))


class _ProgressReporter:
    """진행률을 stderr 한 줄에 갱신한다. 200ms 로 제한해 과도한 출력을 막는다."""

    def __init__(self, interval: float = 0.2) -> None:
        self.interval = interval
        self._last = 0.0
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
