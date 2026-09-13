from ytdl4k.core.models import CodecPolicy, VideoFormat, VideoInfo


def test_from_ytdlp_normalizes_none_codec(raw_4k):
    info = VideoInfo.from_ytdlp(raw_4k)
    audio = next(f for f in info.formats if f.format_id == "251")
    assert audio.vcodec is None and audio.is_audio_only
    assert audio.audio_codec == "opus"


def test_codec_family_strips_profile():
    f = VideoFormat(format_id="401", ext="mp4", vcodec="av01.0.12M.08", acodec=None)
    assert f.video_codec == "av01"
    assert VideoFormat(format_id="313", ext="webm", vcodec="vp09.00.50.08").video_codec == "vp9"
    assert VideoFormat(format_id="140", ext="m4a", acodec="mp4a.40.2").audio_codec == "mp4a"


def test_hdr_detection(info_4k):
    hdr = next(f for f in info_4k.formats if f.format_id == "337")
    sdr = next(f for f in info_4k.formats if f.format_id == "315")
    assert hdr.is_hdr and not sdr.is_hdr


def test_estimated_size_falls_back_to_bitrate():
    f = VideoFormat(format_id="x", ext="webm", vcodec="vp9", height=2160, tbr=19000.0)
    assert f.estimated_size(600) == int(19000 * 1000 / 8 * 600)
    assert f.estimated_size(None) is None


def test_max_height_and_pools(info_4k):
    assert info_4k.max_height == 4320
    assert len(info_4k.audio_formats) == 4
    # progressive(18) 도 video_formats 에 포함된다
    assert any(f.format_id == "18" for f in info_4k.video_formats)


def test_describe_marks_high_fps_and_hdr(info_4k):
    assert next(f for f in info_4k.formats if f.format_id == "315").describe() == "2160p60 vp9"
    assert "HDR" in next(f for f in info_4k.formats if f.format_id == "337").describe()


def test_codec_policy_ranking():
    assert CodecPolicy.QUALITY.video_rank("vp9") > CodecPolicy.QUALITY.video_rank("av01")
    assert CodecPolicy.EFFICIENCY.video_rank("av01") > CodecPolicy.EFFICIENCY.video_rank("vp9")
    assert CodecPolicy.COMPATIBILITY.video_rank("avc1") > CodecPolicy.COMPATIBILITY.video_rank("vp9")
    assert CodecPolicy.COMPATIBILITY.audio_rank("mp4a") > CodecPolicy.COMPATIBILITY.audio_rank("opus")
    assert CodecPolicy.QUALITY.video_rank("h263") == 0
