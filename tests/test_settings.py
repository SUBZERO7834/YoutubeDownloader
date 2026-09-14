from pathlib import Path

from ytdl4k.app.settings import Settings, config_path
from ytdl4k.core.models import CodecPolicy, Container


def test_defaults_are_usable():
    s = Settings()
    assert s.max_height == 2160
    assert s.output_dir.is_absolute()
    assert s.target().codec_policy is CodecPolicy.QUALITY


def test_round_trip(tmp_path):
    original = Settings(
        output_dir=tmp_path / "받은 영상",
        max_height=1440,
        codec_policy=CodecPolicy.EFFICIENCY,
        container=Container.MP4,
        concurrent_downloads=5,
        cookies_from_browser="chrome",
    )
    path = original.save(tmp_path / "config.toml")
    loaded = Settings.load(path)

    assert loaded.output_dir == original.output_dir
    assert loaded.max_height == 1440
    assert loaded.codec_policy is CodecPolicy.EFFICIENCY
    assert loaded.container is Container.MP4
    assert loaded.concurrent_downloads == 5
    assert loaded.cookies_from_browser == "chrome"


def test_missing_file_falls_back_to_defaults(tmp_path):
    assert Settings.load(tmp_path / "없는파일.toml").max_height == 2160


def test_broken_file_does_not_stop_the_app(tmp_path):
    """설정 파일 하나 때문에 앱이 못 뜨면 안 된다."""
    broken = tmp_path / "config.toml"
    broken.write_text("이건 = TOML 이 아님 [[[", encoding="utf-8")
    assert Settings.load(broken) == Settings()


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('max_height = 720\nfuture_plan = "영화감독"\n', encoding="utf-8")
    assert Settings.load(path).max_height == 720


def test_best_quality_is_stored_as_no_limit(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('max_height = "best"\n', encoding="utf-8")
    assert Settings.load(path).max_height is None


def test_no_limit_survives_a_save(tmp_path):
    """'최고 화질' 로 두고 앱을 껐다 켜면 다시 4K 로 돌아가 있으면 안 된다."""
    path = Settings(max_height=None).save(tmp_path / "config.toml")
    assert Settings.load(path).max_height is None


def test_windows_path_survives_toml_escaping(tmp_path):
    s = Settings(output_dir=Path(r"C:\Users\나\Videos"))
    path = s.save(tmp_path / "config.toml")
    assert Settings.load(path).output_dir == Path(r"C:\Users\나\Videos")


def test_config_path_is_under_a_named_folder():
    assert config_path().name == "config.toml"
    assert config_path().parent.name == "ytdl4k"
