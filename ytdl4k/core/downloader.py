"""다운로드 실행.

실제 전송과 병합은 yt-dlp 에 맡기고, 이 모듈은 그 위에서
**진행률 이벤트 · 취소 · 용량 확인 · 결과 검증**을 담당한다.
UI 계층(CLI/GUI)은 ``on_progress`` 콜백만 붙이면 된다.
"""

from __future__ import annotations

import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import DownloadCanceled, DownloadFailed, InsufficientDiskSpace
from .extractor import translate_error
from .formats import Selection
from .merger import FfmpegTools, verify_output
from .models import TaskState, VideoInfo

DEFAULT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"


@dataclass(frozen=True)
class Progress:
    stage: TaskState
    percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_s: int | None = None
    filename: str | None = None


ProgressCallback = Callable[[Progress], None]


class _Canceled(Exception):
    """취소 신호를 yt-dlp 콜스택 밖으로 빼내기 위한 내부 신호."""


class Downloader:
    def __init__(
        self,
        *,
        output_dir: Path,
        base_options: dict[str, Any] | None = None,
        filename_template: str = DEFAULT_TEMPLATE,
        ffmpeg: FfmpegTools | None = None,
        concurrent_fragments: int = 4,
        temp_dir: Path | None = None,
        overwrite: bool = False,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.base_options = base_options or {}
        self.filename_template = filename_template
        self.ffmpeg = ffmpeg
        self.concurrent_fragments = max(1, concurrent_fragments)
        self.temp_dir = temp_dir
        self.overwrite = overwrite
        self.on_progress = on_progress

    # ------------------------------------------------------------------ 공개 API

    def check_space(self, selection: Selection, duration_s: int | None) -> None:
        needed = selection.estimated_size(duration_s)
        if not needed:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(self.output_dir).free
        # 병합 중에는 원본 조각과 결과물이 잠시 함께 존재하므로 2배 + 여유 500MB.
        if free < needed * 2 + 500 * 2**20:
            raise InsufficientDiskSpace(needed * 2, free)

    def download(
        self,
        info: VideoInfo,
        selection: Selection,
        *,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        """선택한 포맷을 내려받고 최종 파일 경로를 돌려준다."""
        import yt_dlp

        self.output_dir.mkdir(parents=True, exist_ok=True)
        opts = self._build_options(selection, cancel_event)

        self._emit(Progress(stage=TaskState.DOWNLOADING))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                result = ydl.extract_info(info.webpage_url, download=True)
                path = self._resolve_path(ydl, result)
        except _Canceled as exc:
            raise DownloadCanceled() from exc
        except Exception as exc:
            if _has_cause(exc, _Canceled):
                raise DownloadCanceled() from exc
            raise translate_error(exc, default=DownloadFailed) from exc

        if path is None:
            raise DownloadFailed("결과 파일 경로를 확인하지 못했습니다.")

        if self.ffmpeg is not None:
            problems = verify_output(
                path,
                self.ffmpeg,
                expect_video=selection.video is not None,
                expect_audio=selection.audio is not None
                or bool(selection.video and selection.video.is_combined),
            )
            if problems:
                raise DownloadFailed(" ".join(problems))

        self._emit(Progress(stage=TaskState.DONE, percent=100.0, filename=str(path)))
        return path

    # ------------------------------------------------------------------ 내부

    def _build_options(self, selection: Selection, cancel_event: threading.Event | None) -> dict[str, Any]:
        opts: dict[str, Any] = dict(self.base_options)
        opts.update(
            {
                "format": selection.format_spec,
                "outtmpl": str(self.output_dir / self.filename_template),
                "progress_hooks": [self._make_hook(cancel_event, TaskState.DOWNLOADING)],
                "postprocessor_hooks": [self._make_pp_hook(cancel_event)],
                "concurrent_fragment_downloads": self.concurrent_fragments,
                "continuedl": True,  # .part 이어받기
                "retries": 10,
                "fragment_retries": 10,
                "noprogress": True,  # 진행률은 우리가 그린다
                "windowsfilenames": True,  # 플랫폼 무관하게 안전한 파일명
                "overwrites": self.overwrite,
            }
        )
        if selection.needs_merge:
            opts["merge_output_format"] = selection.container
        if self.ffmpeg is not None:
            opts["ffmpeg_location"] = self.ffmpeg.location
        if self.temp_dir is not None:
            opts["paths"] = {"home": str(self.output_dir), "temp": str(self.temp_dir)}
        return opts

    def _make_hook(self, cancel_event: threading.Event | None, stage: TaskState):
        def hook(d: dict[str, Any]) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise _Canceled()
            if d.get("status") != "downloading":
                return
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes") or 0
            self._emit(
                Progress(
                    stage=stage,
                    percent=(downloaded / total * 100) if total else 0.0,
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed_bps=d.get("speed"),
                    eta_s=d.get("eta"),
                    filename=d.get("filename"),
                )
            )

        return hook

    def _make_pp_hook(self, cancel_event: threading.Event | None):
        def hook(d: dict[str, Any]) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise _Canceled()
            if d.get("postprocessor") == "Merger" and d.get("status") == "started":
                self._emit(Progress(stage=TaskState.MERGING, percent=99.0))

        return hook

    def _emit(self, progress: Progress) -> None:
        if self.on_progress is not None:
            self.on_progress(progress)

    @staticmethod
    def _resolve_path(ydl: Any, result: dict[str, Any] | None) -> Path | None:
        """yt-dlp 가 실제로 쓴 파일 경로를 찾는다.

        병합 후 확장자가 바뀌므로 템플릿으로 추측하면 틀린다.
        ``requested_downloads`` 가 정답이고, 없을 때만 템플릿으로 되돌아간다.
        """
        if not result:
            return None
        for entry in result.get("requested_downloads") or []:
            filepath = entry.get("filepath") or entry.get("_filename")
            if filepath:
                return Path(filepath)
        guess = Path(ydl.prepare_filename(result))
        if guess.exists():
            return guess
        matches = sorted(guess.parent.glob(f"{glob_escape(guess.stem)}.*"))
        return matches[0] if matches else None


def glob_escape(text: str) -> str:
    return text.translate({ord(c): f"[{c}]" for c in "*?["})


def _has_cause(exc: BaseException, target: type[BaseException]) -> bool:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, target):
            return True
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return False
