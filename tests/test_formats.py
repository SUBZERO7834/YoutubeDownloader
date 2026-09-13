import pytest

from ytdl4k.core.errors import NoSuitableFormat
from ytdl4k.core.formats import list_downloadable, select
from ytdl4k.core.models import CodecPolicy, Container, DownloadTarget


def test_default_picks_4k60_vp9_with_opus(info_4k):
    sel = select(info_4k, DownloadTarget())
    assert sel.video.format_id == "315"  # 2160p60 vp9 (HDR 은 요청 안 했으므로 제외)
    assert sel.audio.format_id == "251"  # 최고 비트레이트 opus
    assert sel.container == "webm"
    assert sel.format_spec == "315+251"
    assert sel.needs_merge


def test_unlimited_quality_picks_8k(info_4k):
    sel = select(info_4k, DownloadTarget(max_height=None))
    assert sel.video.format_id == "272"


def test_height_cap_is_respected(info_4k):
    sel = select(info_4k, DownloadTarget(max_height=1080))
    assert sel.video.height == 1080
    assert sel.video.format_id == "303"  # 같은 1080p 중 60fps


def test_falls_back_to_next_best_height(info_4k):
    # 2000p 짜리는 없으므로 그 아래 최고인 1440p 로 내려간다
    sel = select(info_4k, DownloadTarget(max_height=2000))
    assert sel.video.height == 1440


def test_efficiency_policy_prefers_av1(info_4k):
    sel = select(info_4k, DownloadTarget(codec_policy=CodecPolicy.EFFICIENCY))
    assert sel.video.format_id == "401"
    assert sel.video.video_codec == "av01"


def test_compatibility_policy_prefers_h264_when_available(info_4k):
    sel = select(info_4k, DownloadTarget(max_height=1080, codec_policy=CodecPolicy.COMPATIBILITY))
    assert sel.video.format_id == "137"  # avc1 1080p
    assert sel.audio.format_id == "140"  # AAC
    assert sel.container == "mp4"


def test_mp4_container_forces_mp4_safe_streams(info_4k):
    sel = select(info_4k, DownloadTarget(container=Container.MP4))
    assert sel.video.format_id == "401"  # 4K 에서 mp4 에 무손실로 담기는 것은 av01
    assert sel.audio.format_id == "140"  # opus 대신 AAC
    assert sel.container == "mp4"


def test_mkv_container_is_honored(info_4k):
    sel = select(info_4k, DownloadTarget(container=Container.MKV))
    assert sel.container == "mkv"


def test_prefer_hdr(info_4k):
    sel = select(info_4k, DownloadTarget(prefer_hdr=True))
    assert sel.video.format_id == "337"
    assert sel.video.is_hdr


def test_without_ffmpeg_only_progressive(info_4k):
    sel = select(info_4k, DownloadTarget(), can_merge=False)
    assert sel.video.format_id == "18"
    assert sel.audio is None
    assert not sel.needs_merge
    assert sel.format_spec == "18"
    assert sel.container == "mp4"


def test_audio_only(info_4k):
    sel = select(info_4k, DownloadTarget(audio_only=True))
    assert sel.video is None
    assert sel.audio.format_id == "251"
    assert sel.container == "webm"


def test_audio_only_compatibility_picks_aac(info_4k):
    sel = select(info_4k, DownloadTarget(audio_only=True, codec_policy=CodecPolicy.COMPATIBILITY))
    assert sel.audio.format_id == "140"


def test_no_suitable_format_reports_actual_max(info_4k):
    with pytest.raises(NoSuitableFormat) as err:
        select(info_4k, DownloadTarget(max_height=240))
    assert "4320p" in err.value.full_message


def test_estimated_size_sums_both_streams(info_4k):
    sel = select(info_4k, DownloadTarget())
    assert sel.estimated_size(600) == 1425000000 + 10600000


def test_list_downloadable_is_one_per_height_descending(info_4k):
    rows = list_downloadable(info_4k)
    heights = [f.height for f in rows]
    assert heights == sorted(heights, reverse=True)
    assert len(heights) == len(set(heights))
    assert next(f for f in rows if f.height == 2160).format_id == "315"


def test_mixed_codecs_fall_back_to_mkv(info_4k):
    from ytdl4k.core.formats import pick_container

    video = next(f for f in info_4k.formats if f.format_id == "137")  # avc1
    audio = next(f for f in info_4k.formats if f.format_id == "251")  # opus
    assert pick_container(video, audio, DownloadTarget()) == "mkv"


def test_describe_is_human_readable(info_4k):
    sel = select(info_4k, DownloadTarget())
    assert sel.describe() == "2160p60 vp9 + opus 141k → .webm"
