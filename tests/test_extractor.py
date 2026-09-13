import sys
import types

import pytest

from ytdl4k.core.errors import (
    DownloadFailed,
    DrmProtected,
    ExtractionFailed,
    LoginRequired,
    NetworkError,
    PlaylistNotSupported,
    VideoUnavailable,
)
from ytdl4k.core.extractor import YtDlpExtractor, translate_error


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ERROR: Private video. Sign in if you have been granted access", VideoUnavailable),
        ("ERROR: Video unavailable. This video has been removed", VideoUnavailable),
        ("ERROR: The uploader has not made this video available in your country", VideoUnavailable),
        ("ERROR: Sign in to confirm your age", LoginRequired),
        ("ERROR: Join this channel to get access to members-only content", LoginRequired),
        ("ERROR: Sign in to confirm you're not a bot", LoginRequired),
        ("This video is protected by DRM", DrmProtected),
        ("ERROR: Unable to extract nsig function; please report this issue", ExtractionFailed),
    ],
)
def test_translate_error_maps_known_messages(message, expected):
    assert isinstance(translate_error(Exception(message)), expected)


def test_translate_error_uses_context_default():
    assert isinstance(translate_error(Exception("소켓 끊김"), default=DownloadFailed), DownloadFailed)


def test_translate_error_passes_through_app_errors():
    original = DrmProtected()
    assert translate_error(original) is original


class _FakeYoutubeDL:
    """extract_info 만 흉내 내는 최소 대역. 네트워크를 타지 않는다."""

    result: dict | None = None
    raises: Exception | None = None

    def __init__(self, opts):
        self.opts = opts
        type(self).last_opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if type(self).raises:
            raise type(self).raises
        return type(self).result


@pytest.fixture
def fake_ytdlp(monkeypatch):
    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = _FakeYoutubeDL
    _FakeYoutubeDL.result = None
    _FakeYoutubeDL.raises = None
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    return _FakeYoutubeDL


def test_extract_returns_normalized_info(fake_ytdlp, raw_4k):
    fake_ytdlp.result = raw_4k
    info = YtDlpExtractor().extract("https://youtu.be/dQw4w9WgXcQ")
    assert info.id == "dQw4w9WgXcQ"
    assert info.max_height == 4320


def test_extract_rejects_multi_entry_playlist(fake_ytdlp, raw_4k):
    fake_ytdlp.result = {"_type": "playlist", "entries": [raw_4k, raw_4k]}
    with pytest.raises(PlaylistNotSupported):
        YtDlpExtractor().extract("https://youtube.com/playlist?list=X")


def test_extract_unwraps_single_entry_playlist(fake_ytdlp, raw_4k):
    fake_ytdlp.result = {"_type": "playlist", "entries": [raw_4k]}
    assert YtDlpExtractor().extract("url").id == "dQw4w9WgXcQ"


def test_extract_rejects_drm(fake_ytdlp, raw_4k):
    fake_ytdlp.result = dict(raw_4k, _has_drm=True)
    with pytest.raises(DrmProtected):
        YtDlpExtractor().extract("url")


def test_extract_translates_exceptions(fake_ytdlp):
    fake_ytdlp.raises = Exception("ERROR: Sign in to confirm your age")
    with pytest.raises(LoginRequired):
        YtDlpExtractor().extract("url")


def test_extract_rejects_empty_result(fake_ytdlp):
    fake_ytdlp.result = None
    with pytest.raises(ExtractionFailed):
        YtDlpExtractor().extract("url")


def test_cookie_options_are_passed_through():
    opts = YtDlpExtractor(cookies_from_browser="chrome", cookie_file="/tmp/c.txt").base_options()
    assert opts["cookiesfrombrowser"] == ("chrome", None, None, None)
    assert opts["cookiefile"] == "/tmp/c.txt"
    assert opts["noplaylist"] is True


def test_no_cookie_options_by_default():
    opts = YtDlpExtractor().base_options()
    assert "cookiesfrombrowser" not in opts and "cookiefile" not in opts


@pytest.mark.parametrize(
    "message",
    [
        "Unable to download API page: <urlopen error Tunnel connection failed: 403 Forbidden>",
        "ERROR: [youtube] Unable to download webpage: <urlopen error timed out>",
        "ERROR: Unable to download: Temporary failure in name resolution",
        "ERROR: certificate verify failed: unable to get local issuer certificate",
    ],
)
def test_network_errors_are_not_blamed_on_youtube(message):
    """연결 실패를 'YouTube 사양 변경' 으로 안내하면 사용자가 엉뚱한 곳을 고치게 된다."""
    err = translate_error(Exception(message))
    assert isinstance(err, NetworkError)
    assert "네트워크" in err.message
