"""도메인 모델.

yt-dlp가 돌려주는 헐거운 dict 를 여기서 한 번만 정규화한다.
이 아래 레이어(포맷 선택·CLI·GUI)는 yt-dlp 의 키 이름을 몰라도 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# yt-dlp 는 "없음"을 None 이 아니라 문자열 'none' 으로 준다.
_NONE = ("none", "", None)


def _codec_family(codec: str | None) -> str | None:
    """'avc1.640028' → 'avc1', 'av01.0.12M.08' → 'av01' 처럼 앞부분만 남긴다."""
    if codec in _NONE:
        return None
    base = str(codec).split(".")[0].lower()
    return {"vp09": "vp9", "mp4a": "mp4a", "ec-3": "eac3"}.get(base, base)


@dataclass(frozen=True)
class VideoFormat:
    format_id: str
    ext: str
    vcodec: str | None = None
    acodec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    dynamic_range: str | None = None
    filesize: int | None = None
    tbr: float | None = None
    format_note: str | None = None

    @classmethod
    def from_ytdlp(cls, raw: dict[str, Any]) -> VideoFormat:
        return cls(
            format_id=str(raw.get("format_id", "")),
            ext=str(raw.get("ext", "")),
            vcodec=None if raw.get("vcodec") in _NONE else str(raw["vcodec"]),
            acodec=None if raw.get("acodec") in _NONE else str(raw["acodec"]),
            width=raw.get("width"),
            height=raw.get("height"),
            fps=raw.get("fps"),
            dynamic_range=raw.get("dynamic_range"),
            filesize=raw.get("filesize") or raw.get("filesize_approx"),
            tbr=raw.get("tbr"),
            format_note=raw.get("format_note"),
        )

    @property
    def is_video_only(self) -> bool:
        return self.vcodec is not None and self.acodec is None

    @property
    def is_audio_only(self) -> bool:
        return self.acodec is not None and self.vcodec is None

    @property
    def is_combined(self) -> bool:
        return self.vcodec is not None and self.acodec is not None

    @property
    def video_codec(self) -> str | None:
        return _codec_family(self.vcodec)

    @property
    def audio_codec(self) -> str | None:
        return _codec_family(self.acodec)

    @property
    def is_hdr(self) -> bool:
        dr = (self.dynamic_range or "SDR").upper()
        return dr not in ("SDR", "NONE", "")

    def estimated_size(self, duration_s: int | None) -> int | None:
        """filesize 가 없으면 비트레이트×길이로 어림한다 (DASH 는 종종 비어 있다)."""
        if self.filesize:
            return self.filesize
        if self.tbr and duration_s:
            return int(self.tbr * 1000 / 8 * duration_s)
        return None

    def describe(self) -> str:
        if self.is_audio_only:
            bitrate = f"{self.tbr:.0f}k" if self.tbr else "?"
            return f"{self.audio_codec} {bitrate}"
        res = f"{self.height}p" if self.height else "?"
        if self.fps and self.fps >= 50:
            res += f"{self.fps:.0f}"
        hdr = " HDR" if self.is_hdr else ""
        return f"{res}{hdr} {self.video_codec}"


@dataclass(frozen=True)
class VideoInfo:
    id: str
    title: str
    duration: int | None
    uploader: str | None
    thumbnail_url: str | None
    webpage_url: str
    formats: list[VideoFormat] = field(default_factory=list)
    is_live: bool = False
    has_drm: bool = False

    @classmethod
    def from_ytdlp(cls, raw: dict[str, Any]) -> VideoInfo:
        formats = [VideoFormat.from_ytdlp(f) for f in raw.get("formats") or []]
        return cls(
            id=str(raw.get("id", "")),
            title=str(raw.get("title", "")),
            duration=raw.get("duration"),
            uploader=raw.get("uploader") or raw.get("channel"),
            thumbnail_url=raw.get("thumbnail"),
            webpage_url=raw.get("webpage_url") or raw.get("original_url") or "",
            formats=formats,
            is_live=bool(raw.get("is_live")),
            has_drm=bool(raw.get("_has_drm")) or any(f.get("has_drm") for f in raw.get("formats") or []),
        )

    @property
    def video_formats(self) -> list[VideoFormat]:
        return [f for f in self.formats if f.vcodec and f.height]

    @property
    def audio_formats(self) -> list[VideoFormat]:
        return [f for f in self.formats if f.is_audio_only]

    @property
    def max_height(self) -> int | None:
        heights = [f.height for f in self.video_formats if f.height]
        return max(heights) if heights else None


class CodecPolicy(StrEnum):
    """코덱 선호 정책 (docs/PLAN.md §2)."""

    QUALITY = "quality"  # VP9 우선 — 4K + 하드웨어 디코딩 보급률
    EFFICIENCY = "efficiency"  # AV1 우선 — 같은 화질에 용량이 작다
    COMPATIBILITY = "compatibility"  # H.264 우선 — 구형 기기·편집기 호환

    def video_rank(self, codec: str | None) -> int:
        order = {
            CodecPolicy.QUALITY: ["vp9", "av01", "avc1"],
            CodecPolicy.EFFICIENCY: ["av01", "vp9", "avc1"],
            CodecPolicy.COMPATIBILITY: ["avc1", "av01", "vp9"],
        }[self]
        return len(order) - order.index(codec) if codec in order else 0

    def audio_rank(self, codec: str | None) -> int:
        order = ["mp4a", "opus"] if self is CodecPolicy.COMPATIBILITY else ["opus", "mp4a"]
        return len(order) - order.index(codec) if codec in order else 0


class ThumbnailMode(StrEnum):
    """썸네일을 어떻게 할지."""

    NONE = "none"  # 받지 않는다
    FILE = "file"  # 영상 옆에 그림 파일로 저장
    EMBED = "embed"  # 영상·음원 안에 표지로 넣는다


class Container(StrEnum):
    AUTO = "auto"
    MP4 = "mp4"
    MKV = "mkv"


class TaskState(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    DOWNLOADING = "downloading"
    MERGING = "merging"
    DONE = "done"
    FAILED = "failed"
    CANCELED = "canceled"


@dataclass(frozen=True)
class DownloadTarget:
    """'무엇을 받고 싶은가' 를 담은 요청. 해석은 core.formats 가 한다."""

    max_height: int | None = 2160  # None 이면 화질 무제한(최고화질)
    codec_policy: CodecPolicy = CodecPolicy.QUALITY
    container: Container = Container.AUTO
    audio_only: bool = False
    prefer_hdr: bool = False
    thumbnail: ThumbnailMode = ThumbnailMode.NONE
