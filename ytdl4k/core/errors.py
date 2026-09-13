"""도메인 예외.

설계 원칙(docs/ARCHITECTURE.md §6): 모든 실패는 **원인**만이 아니라
**사용자에게 보일 메시지**와 **다음 행동**을 함께 들고 다닌다.
UI 계층은 예외 종류를 몰라도 ``str(err)`` 와 ``err.hint`` 만 띄우면 된다.
"""

from __future__ import annotations


class AppError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        return self.message

    @property
    def full_message(self) -> str:
        return f"{self.message}\n{self.hint}" if self.hint else self.message


class ExtractionFailed(AppError):
    """영상 정보를 읽지 못함. 대개 YouTube 사양 변경이 원인."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            "영상 정보를 가져오지 못했습니다.",
            hint="YouTube 변경으로 추출에 실패했을 수 있습니다. yt-dlp를 최신으로 업데이트해 주세요."
            f"\n원본 오류: {detail}",
        )


class NetworkError(AppError):
    """연결 자체가 실패. YouTube 사양 변경과는 원인도 해법도 다르므로 분리한다."""

    def __init__(self, detail: str) -> None:
        super().__init__(
            "네트워크에 연결하지 못했습니다.",
            hint=f"인터넷 연결, 프록시, 방화벽 설정을 확인해 주세요.\n원본 오류: {detail}",
        )


class VideoUnavailable(AppError):
    """비공개·삭제·지역 제한 등으로 접근 불가."""

    def __init__(self, detail: str) -> None:
        super().__init__("영상을 볼 수 없습니다.", hint=detail)


class LoginRequired(AppError):
    """연령 제한·멤버십 등 로그인이 필요한 영상."""

    def __init__(self, detail: str = "") -> None:
        super().__init__(
            "로그인이 필요한 영상입니다.",
            hint="브라우저 쿠키를 연결해 주세요. 예: --cookies-from-browser chrome"
            + (f"\n원본 오류: {detail}" if detail else ""),
        )


class DrmProtected(AppError):
    """DRM 보호 콘텐츠 — 지원하지 않으며 우회도 하지 않는다."""

    def __init__(self) -> None:
        super().__init__(
            "보호된(DRM) 콘텐츠는 지원하지 않습니다.",
            hint="이 도구는 DRM 우회 기능을 제공하지 않습니다.",
        )


class PlaylistNotSupported(AppError):
    """재생목록은 M2 범위. 지금은 개별 영상 URL만 받는다."""

    def __init__(self) -> None:
        super().__init__(
            "재생목록 URL은 아직 지원하지 않습니다.",
            hint="개별 영상 URL을 입력하거나, 재생목록 안의 영상 주소를 사용해 주세요.",
        )


class NoSuitableFormat(AppError):
    """요청한 조건을 만족하는 포맷이 없음."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message, hint=hint)

    @classmethod
    def for_height(cls, requested: int, available: int | None) -> NoSuitableFormat:
        if available is None:
            return cls(
                "이 영상에서 받을 수 있는 영상 스트림을 찾지 못했습니다.",
                hint="라이브 스트림이거나 일시적인 제공 중단일 수 있습니다.",
            )
        return cls(
            f"{requested}p 이하의 화질을 찾지 못했습니다.",
            hint=f"이 영상의 최고 화질은 {available}p 입니다.",
        )


class FfmpegNotFound(AppError):
    """4K 병합에 필수인 ffmpeg을 찾지 못함."""

    def __init__(self) -> None:
        super().__init__(
            "ffmpeg을 찾을 수 없습니다.",
            hint="1080p를 넘는 화질은 영상과 음성이 분리되어 제공되므로 병합에 ffmpeg이 필요합니다. "
            "ffmpeg을 설치하거나 --ffmpeg-location 으로 경로를 지정해 주세요.",
        )


class DownloadFailed(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__("다운로드에 실패했습니다.", hint=detail)


class DownloadCanceled(AppError):
    """사용자 취소. ``.part`` 파일은 남겨 두어 이어받기에 쓴다."""

    def __init__(self) -> None:
        super().__init__(
            "다운로드를 취소했습니다.",
            hint="받던 조각은 남겨 두었습니다. 같은 설정으로 다시 실행하면 이어받습니다.",
        )


class InsufficientDiskSpace(AppError):
    """저장 공간 부족 — 8GB 짜리 4K 를 다 받고 나서 실패하는 일을 막는다."""

    def __init__(self, needed: int, available: int) -> None:
        super().__init__(
            "저장 공간이 부족합니다.",
            hint=f"예상 용량 {needed / 2**30:.1f}GB, 남은 공간 {available / 2**30:.1f}GB 입니다.",
        )
