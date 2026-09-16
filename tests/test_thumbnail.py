"""썸네일 처리 검증.

핵심은 '넣을 수 없는 조합에서 실패하지 않는 것' 이다. 표지는 부가 기능인데
그것 때문에 영상을 못 받게 되면 안 된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ytdl4k.core.downloader import Downloader, can_embed_thumbnail, embed_blocker
from ytdl4k.core.errors import PostProcessingFailed
from ytdl4k.core.extractor import translate_error
from ytdl4k.core.formats import select
from ytdl4k.core.merger import FfmpegTools
from ytdl4k.core.models import CodecPolicy, Container, DownloadTarget, ThumbnailMode

FULL = FfmpegTools(Path("/usr/bin/ffmpeg"), Path("/usr/bin/ffprobe"))
NO_PROBE = FfmpegTools(Path("/usr/bin/ffmpeg"), None)


# ── 컨테이너 선택 ────────────────────────────────────────────────────────


def test_embedding_moves_webm_to_mkv(info_4k):
    """yt-dlp 는 webm 에 표지를 넣지 못한다. 같은 스트림을 mkv 에 담으면 된다."""
    plain = select(info_4k, DownloadTarget())
    embed = select(info_4k, DownloadTarget(thumbnail=ThumbnailMode.EMBED))

    assert plain.container == "webm"
    assert embed.container == "mkv"
    assert embed.format_spec == plain.format_spec, "화질·코덱은 그대로여야 한다"


def test_mp4_stays_mp4_when_embedding(info_4k):
    embed = select(info_4k, DownloadTarget(container=Container.MP4, thumbnail=ThumbnailMode.EMBED))
    assert embed.container == "mp4"


def test_saving_as_a_file_does_not_change_the_container(info_4k):
    """그림 파일로 따로 저장할 때는 컨테이너를 건드릴 이유가 없다."""
    assert select(info_4k, DownloadTarget(thumbnail=ThumbnailMode.FILE)).container == "webm"


def test_audio_only_embedding_picks_aac(info_4k):
    """opus 는 webm 에 담겨 표지를 못 넣는다. YouTube 가 함께 주는 AAC 를 고른다."""
    plain = select(info_4k, DownloadTarget(audio_only=True))
    embed = select(info_4k, DownloadTarget(audio_only=True, thumbnail=ThumbnailMode.EMBED))

    assert plain.audio.audio_codec == "opus" and plain.container == "webm"
    assert embed.audio.audio_codec == "mp4a" and embed.container == "m4a"


def test_audio_only_embedding_does_not_reencode(info_4k):
    """코덱을 바꾸는 것이 아니라 다른 트랙을 고르는 것뿐이다."""
    embed = select(info_4k, DownloadTarget(audio_only=True, thumbnail=ThumbnailMode.EMBED))
    assert embed.audio.format_id in {f.format_id for f in info_4k.audio_formats}


# ── 넣을 수 있는지 판정 ──────────────────────────────────────────────────


def test_mp4_needs_mutagen():
    assert embed_blocker("mp4", FULL) is None
    assert can_embed_thumbnail("m4a", NO_PROBE), "mp4 계열은 ffprobe 없이도 된다"


def test_mp4_without_mutagen_is_blocked(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert "mutagen" in embed_blocker("mp4", FULL)


def test_mkv_needs_ffprobe():
    assert embed_blocker("mkv", FULL) is None
    blocker = embed_blocker("mkv", NO_PROBE)
    assert blocker is not None and "ffprobe" in blocker


def test_webm_cannot_hold_a_thumbnail_at_all():
    blocker = embed_blocker("webm", FULL)
    assert blocker is not None and "webm" in blocker


def test_without_ffmpeg_nothing_can_be_embedded():
    assert "ffmpeg" in embed_blocker("mp4", None)


@pytest.mark.parametrize(
    ("container", "tools"),
    [("webm", FULL), ("mkv", NO_PROBE), ("mp4", None)],
)
def test_blocked_embedding_falls_back_to_a_file(tmp_path, info_4k, container, tools):
    """막히면 실패가 아니라 그림 파일로 저장한다 — 영상까지 잃으면 안 된다."""
    downloader = Downloader(output_dir=tmp_path, ffmpeg=tools, thumbnail=ThumbnailMode.EMBED)
    selection = select(info_4k, DownloadTarget(container=Container.MKV))
    object.__setattr__(selection, "container", container)

    assert downloader.effective_thumbnail(selection) is ThumbnailMode.FILE


# ── yt-dlp 옵션 ─────────────────────────────────────────────────────────


def build_options(tmp_path, mode: ThumbnailMode, info_4k, tools=FULL):
    downloader = Downloader(output_dir=tmp_path, ffmpeg=tools, thumbnail=mode)
    selection = select(info_4k, DownloadTarget(thumbnail=mode))
    return downloader._build_options(selection, None)


def test_embed_mode_sets_the_postprocessor(tmp_path, info_4k):
    opts = build_options(tmp_path, ThumbnailMode.EMBED, info_4k)
    assert opts["writethumbnail"] is True
    assert [p["key"] for p in opts["postprocessors"]] == ["EmbedThumbnail"]
    assert opts["postprocessors"][0]["already_have_thumbnail"] is False, "넣은 뒤 그림 파일은 지운다"


def test_file_mode_only_saves_the_picture(tmp_path, info_4k):
    opts = build_options(tmp_path, ThumbnailMode.FILE, info_4k)
    assert opts["writethumbnail"] is True
    assert "postprocessors" not in opts


def test_none_mode_asks_for_nothing(tmp_path, info_4k):
    opts = build_options(tmp_path, ThumbnailMode.NONE, info_4k)
    assert "writethumbnail" not in opts
    assert "postprocessors" not in opts


def test_blocked_embed_downgrades_the_options(tmp_path, info_4k):
    opts = build_options(tmp_path, ThumbnailMode.EMBED, info_4k, tools=NO_PROBE)
    assert opts["writethumbnail"] is True  # 그림은 받되
    assert "postprocessors" not in opts  # 넣으려 시도하지는 않는다


# ── 오류 분류 ───────────────────────────────────────────────────────────


def test_postprocessing_failure_is_its_own_error():
    """받기는 끝난 뒤의 실패다. '다운로드 실패' 로 뭉뚱그리면 파일을 찾지 못한다."""
    err = translate_error(
        Exception("ERROR: Postprocessing: Unable to embed using ffprobe & ffmpeg; ffprobe not found")
    )
    assert isinstance(err, PostProcessingFailed)
    assert "저장 폴더" in err.hint


# ── 설정 ────────────────────────────────────────────────────────────────


def test_thumbnail_setting_survives_a_restart(tmp_path):
    from ytdl4k.app.settings import Settings

    path = Settings(output_dir=tmp_path, thumbnail=ThumbnailMode.EMBED).save(tmp_path / "config.toml")
    loaded = Settings.load(path)
    assert loaded.thumbnail is ThumbnailMode.EMBED
    assert loaded.target().thumbnail is ThumbnailMode.EMBED


def test_codec_policy_still_wins_within_the_same_container(info_4k):
    """표지 때문에 화질 정책이 뒤집히면 안 된다."""
    embed = select(
        info_4k, DownloadTarget(codec_policy=CodecPolicy.EFFICIENCY, thumbnail=ThumbnailMode.EMBED)
    )
    assert embed.video.video_codec == "av01"
