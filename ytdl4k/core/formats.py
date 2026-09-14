"""포맷 선택 — 이 프로젝트의 심장.

네트워크를 타지 않는 **순수 함수**로만 구성한다. 덕분에 고정된 포맷 JSON
픽스처만으로 전부 단위 테스트할 수 있고, YouTube 사양이 바뀌어도
이 로직의 테스트는 계속 유효하다 (docs/ARCHITECTURE.md §4).
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import NoSuitableFormat
from .models import Container, DownloadTarget, VideoFormat, VideoInfo

# 컨테이너별 "재생 호환성이 검증된" 코덱 조합.
# ffmpeg 7.x 는 vp9+opus 를 mp4 에 담는 것도 허용하므로 이 목록은 먹싱 가능 여부가 아니라
# 실제 플레이어·기기에서 문제없이 재생되는 조합인지를 기준으로 한다.
_MP4_SAFE_VIDEO = {"avc1", "av01"}
_MP4_SAFE_AUDIO = {"mp4a"}
_WEBM_SAFE_VIDEO = {"vp9", "av01"}
_WEBM_SAFE_AUDIO = {"opus"}


@dataclass(frozen=True)
class Selection:
    """무엇을 받을지 확정된 결과."""

    video: VideoFormat | None
    audio: VideoFormat | None
    container: str

    @property
    def needs_merge(self) -> bool:
        return self.video is not None and self.audio is not None

    @property
    def format_spec(self) -> str:
        """yt-dlp 에 넘길 포맷 문자열. 예: '313+251'"""
        ids = [f.format_id for f in (self.video, self.audio) if f is not None]
        if not ids:
            raise ValueError("빈 선택은 포맷 문자열로 바꿀 수 없습니다")
        return "+".join(ids)

    @property
    def height(self) -> int | None:
        return self.video.height if self.video else None

    def estimated_size(self, duration_s: int | None) -> int | None:
        sizes = [f.estimated_size(duration_s) for f in (self.video, self.audio) if f is not None]
        return sum(s for s in sizes if s) if any(sizes) else None

    def describe(self) -> str:
        parts = [f.describe() for f in (self.video, self.audio) if f is not None]
        return f"{' + '.join(parts)} → .{self.container}"


def select(info: VideoInfo, target: DownloadTarget, *, can_merge: bool = True) -> Selection:
    """``target`` 에 맞는 최적 조합을 고른다.

    can_merge=False (ffmpeg 없음) 면 영상+음성이 한 파일에 들어 있는
    progressive 포맷만 후보로 삼는다. 4K 는 그런 포맷이 존재하지 않으므로
    사실상 720p 로 제한되지만, 실패하는 대신 받을 수 있는 것을 받게 한다.
    """
    if target.audio_only:
        return _select_audio_only(info, target)

    candidates = [
        f
        for f in info.video_formats
        if (target.max_height is None or (f.height or 0) <= target.max_height)
        and (can_merge or f.is_combined)
    ]
    if not candidates:
        pool = info.video_formats if can_merge else [f for f in info.video_formats if f.is_combined]
        available = max((f.height or 0 for f in pool), default=None)
        raise NoSuitableFormat.for_height(target.max_height or 0, available or None)

    best_height = max(f.height or 0 for f in candidates)
    video = max(
        (f for f in candidates if f.height == best_height),
        key=lambda f: _video_key(f, target),
    )

    audio = None if video.is_combined else _best_audio(info, target, video)
    container = pick_container(video, audio, target)
    return Selection(video=video, audio=audio, container=container)


def _select_audio_only(info: VideoInfo, target: DownloadTarget) -> Selection:
    audios = info.audio_formats
    if not audios:
        raise NoSuitableFormat(
            "오디오 전용 스트림을 찾지 못했습니다.",
            hint="영상까지 받은 뒤 오디오를 추출해야 할 수 있습니다.",
        )
    audio = max(audios, key=lambda f: (target.codec_policy.audio_rank(f.audio_codec), f.tbr or 0))
    return Selection(video=None, audio=audio, container=_audio_container(audio))


def _audio_container(audio: VideoFormat) -> str:
    """오디오 전용 파일의 확장자.

    내용물이 같아도 .mp4 로 저장하면 음악 앱·플레이어가 영상으로 다루는 경우가 있다.
    AAC 는 .m4a 로 내보내는 것이 관례다.
    """
    ext = (audio.ext or "").lower()
    if ext in ("mp4", "m4a") or audio.audio_codec == "mp4a":
        return "m4a"
    return ext or "webm"


def _best_audio(info: VideoInfo, target: DownloadTarget, video: VideoFormat) -> VideoFormat | None:
    audios = info.audio_formats
    if not audios:
        return None
    return max(audios, key=lambda f: _audio_key(f, target, video))


def _video_key(f: VideoFormat, target: DownloadTarget) -> tuple:
    """같은 해상도 안에서의 우선순위: HDR 여부 → 컨테이너 적합성 → 코덱 → fps → 비트레이트.

    HDR 항은 **양방향**이다. HDR 스트림은 비트레이트가 더 높아서 가만히 두면
    요청하지 않아도 뽑히는데, SDR 화면에서 재생하면 색이 바래 보인다.
    그래서 요청했을 때만 우대하고, 요청하지 않았으면 SDR 을 우대한다.
    """
    hdr = 1 if (target.prefer_hdr == f.is_hdr) else 0
    fit = _container_fit_video(f, target.container)
    return (hdr, fit, target.codec_policy.video_rank(f.video_codec), f.fps or 0, f.tbr or 0)


def _audio_key(f: VideoFormat, target: DownloadTarget, video: VideoFormat) -> tuple:
    """컨테이너 적합성이 코덱 선호보다 우선 — 재인코딩 없이 담기는 조합을 고른다."""
    container = target.container
    if container is Container.AUTO:
        # 영상 코덱이 사실상 컨테이너를 정하므로 거기에 맞춘다.
        want_mp4 = (video.video_codec in _MP4_SAFE_VIDEO) and video.video_codec != "av01"
        fit = 1 if (f.audio_codec in (_MP4_SAFE_AUDIO if want_mp4 else _WEBM_SAFE_AUDIO)) else 0
    elif container is Container.MP4:
        fit = 1 if f.audio_codec in _MP4_SAFE_AUDIO else 0
    else:
        fit = 0
    return (fit, target.codec_policy.audio_rank(f.audio_codec), f.tbr or 0)


def _container_fit_video(f: VideoFormat, container: Container) -> int:
    if container is Container.MP4:
        return 1 if f.video_codec in _MP4_SAFE_VIDEO else 0
    return 0  # AUTO/MKV 는 어떤 영상 코덱이든 담을 수 있다


def pick_container(video: VideoFormat | None, audio: VideoFormat | None, target: DownloadTarget) -> str:
    """최종 확장자 결정.

    기본 정책은 **무손실 + 호환성 우선**이다. 재인코딩 없이 담기면서 플레이어가
    가장 탈 없이 재생하는 컨테이너를 고르고, 사용자가 mp4/mkv 를 명시적으로
    강제한 경우에만 그 뜻을 따른다. 어떤 조합이든 mkv 로는 담을 수 있으므로
    mkv 가 마지막 안전망이 된다.
    """
    if video is None:
        return _audio_container(audio) if audio else "m4a"
    if target.container is Container.MP4:
        return "mp4"
    if target.container is Container.MKV:
        return "mkv"

    v = video.video_codec
    a = audio.audio_codec if audio else None
    if video.is_combined:
        return video.ext or "mp4"
    if v in _MP4_SAFE_VIDEO and (a is None or a in _MP4_SAFE_AUDIO):
        return "mp4"
    if v in _WEBM_SAFE_VIDEO and (a is None or a in _WEBM_SAFE_AUDIO):
        return "webm"
    return "mkv"  # 섞인 조합(예: avc1 + opus)은 mkv 가 가장 안전하다


def list_downloadable(info: VideoInfo) -> list[VideoFormat]:
    """사용자에게 보여줄 화질 목록 — 해상도별 최고 하나씩만 추린다."""
    best_per_height: dict[int, VideoFormat] = {}
    target = DownloadTarget()
    for f in info.video_formats:
        h = f.height or 0
        cur = best_per_height.get(h)
        if cur is None or _video_key(f, target) > _video_key(cur, target):
            best_per_height[h] = f
    return [best_per_height[h] for h in sorted(best_per_height, reverse=True)]
