"""URL → VideoInfo.

yt-dlp 를 얇게 감싼다. 감싸는 이유는 두 가지(docs/ARCHITECTURE.md §7):
테스트에서 가짜 구현을 주입하기 위해서, 그리고 추출 엔진을 나중에 교체·이중화
할 수 있게 하기 위해서. 그래서 이 모듈 바깥으로는 yt-dlp 타입이 새어 나가지 않는다.
"""

from __future__ import annotations

from typing import Any, Protocol

from .errors import (
    AppError,
    DrmProtected,
    ExtractionFailed,
    LoginRequired,
    NetworkError,
    PlaylistNotSupported,
    PostProcessingFailed,
    VideoUnavailable,
)
from .models import VideoInfo

# yt-dlp 오류 메시지 → 도메인 예외. 위에서부터 먼저 걸리는 것을 쓴다.
_ERROR_PATTERNS: list[tuple[tuple[str, ...], type[AppError]]] = [
    (("drm", "protected by drm"), DrmProtected),
    (("postprocessing:", "unable to embed"), PostProcessingFailed),
    (
        (
            "proxyerror",
            "tunnel connection failed",
            "urlopen error",
            "connection refused",
            "connection reset",
            "network is unreachable",
            "name resolution",
            "timed out",
            "certificate verify failed",
        ),
        NetworkError,
    ),
    (
        (
            "sign in to confirm your age",
            "age-restricted",
            "members-only",
            "join this channel",
            "sign in to confirm you're not a bot",
            "requires payment",
            "login required",
        ),
        LoginRequired,
    ),
    (
        (
            "private video",
            "video unavailable",
            "no longer available",
            "has been removed",
            "available in your country",  # "not available…" / "has not made this video available…"
            "blocked it in your country",
            "account associated with this video has been terminated",
        ),
        VideoUnavailable,
    ),
]


class Extractor(Protocol):
    def extract(self, url: str) -> VideoInfo: ...


class YtDlpExtractor:
    def __init__(
        self,
        *,
        cookies_from_browser: str | None = None,
        cookie_file: str | None = None,
        quiet: bool = True,
    ) -> None:
        self.cookies_from_browser = cookies_from_browser
        self.cookie_file = cookie_file
        self.quiet = quiet

    def base_options(self) -> dict[str, Any]:
        """추출·다운로드가 공유하는 yt-dlp 옵션."""
        opts: dict[str, Any] = {
            "quiet": self.quiet,
            "no_warnings": self.quiet,
            "noplaylist": True,
            "extract_flat": False,
        }
        if self.cookies_from_browser:
            # yt-dlp 형식: (browser, profile, keyring, container)
            opts["cookiesfrombrowser"] = (self.cookies_from_browser, None, None, None)
        if self.cookie_file:
            opts["cookiefile"] = self.cookie_file
        return opts

    def extract(self, url: str) -> VideoInfo:
        import yt_dlp

        opts = self.base_options()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                raw = ydl.extract_info(url, download=False)
        except Exception as exc:  # yt-dlp 예외 계층을 밖으로 흘리지 않는다
            raise translate_error(exc) from exc

        if raw is None:
            raise ExtractionFailed("yt-dlp 가 아무 정보도 돌려주지 않았습니다.")
        if raw.get("_type") in ("playlist", "multi_video"):
            entries = [e for e in (raw.get("entries") or []) if e]
            if len(entries) != 1:
                raise PlaylistNotSupported()
            raw = entries[0]

        info = VideoInfo.from_ytdlp(raw)
        if info.has_drm:
            raise DrmProtected()
        return info


def translate_error(exc: Exception, *, default: type[AppError] = ExtractionFailed) -> AppError:
    """yt-dlp 오류를 '사용자가 다음에 뭘 하면 되는지' 가 담긴 오류로 바꾼다.

    ``default`` 는 패턴에 걸리지 않았을 때 쓸 예외 — 추출 단계면 ExtractionFailed,
    다운로드 단계면 DownloadFailed 처럼 호출 측이 문맥을 정한다.
    """
    if isinstance(exc, AppError):
        return exc
    message = str(exc)
    lowered = message.lower()
    for needles, error_cls in _ERROR_PATTERNS:
        if any(n in lowered for n in needles):
            if error_cls is DrmProtected:
                return DrmProtected()
            return error_cls(message)
    return default(message)
