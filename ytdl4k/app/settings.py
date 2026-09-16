"""사용자 설정.

GUI 와 CLI 가 같은 파일을 읽는다. 형식은 TOML — 사람이 직접 열어 고칠 수 있고,
읽기는 표준 라이브러리(tomllib)로 충분하다. 쓰기는 값이 전부 평범한 스칼라라
작은 직렬화기로 해결한다(의존성 추가 없이).
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from ..core.downloader import DEFAULT_TEMPLATE
from ..core.models import CodecPolicy, Container, DownloadTarget, ThumbnailMode

APP_NAME = "ytdl4k"


def config_dir() -> Path:
    """플랫폼별 설정 폴더."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.toml"


def default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


@dataclass
class Settings:
    output_dir: Path = None  # type: ignore[assignment]
    max_height: int | None = 2160
    codec_policy: CodecPolicy = CodecPolicy.QUALITY
    container: Container = Container.AUTO
    audio_only: bool = False
    prefer_hdr: bool = False
    thumbnail: ThumbnailMode = ThumbnailMode.NONE
    concurrent_downloads: int = 3
    concurrent_fragments: int = 4
    filename_template: str = DEFAULT_TEMPLATE
    cookies_from_browser: str | None = None
    overwrite: bool = False

    def __post_init__(self) -> None:
        if self.output_dir is None:
            self.output_dir = default_output_dir()
        self.output_dir = Path(self.output_dir).expanduser()
        self.codec_policy = CodecPolicy(self.codec_policy)
        self.container = Container(self.container)
        self.thumbnail = ThumbnailMode(self.thumbnail)

    def target(self) -> DownloadTarget:
        """설정에서 '무엇을 받을지' 요청을 만든다."""
        return DownloadTarget(
            max_height=self.max_height,
            codec_policy=self.codec_policy,
            container=self.container,
            audio_only=self.audio_only,
            prefer_hdr=self.prefer_hdr,
            thumbnail=self.thumbnail,
        )

    # ------------------------------------------------------------------ 저장/불러오기

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """설정을 읽는다. 파일이 없거나 깨졌으면 기본값으로 돌아간다.

        설정 파일 하나 때문에 앱이 못 뜨는 일은 없어야 한다.
        """
        path = path or config_path()
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return cls()

        known = {f.name for f in fields(cls)}
        values: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
        if values.get("max_height") in (0, "best", "none"):
            values["max_height"] = None
        try:
            return cls(**values)
        except (TypeError, ValueError):
            return cls()

    def save(self, path: Path | None = None) -> Path:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_toml(), encoding="utf-8")
        return path

    def to_toml(self) -> str:
        lines = ["# ytdl4k 설정 — 직접 고쳐도 됩니다.", ""]
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "max_height" and value is None:
                # TOML 에는 null 이 없다. 주석 처리해 버리면 다음에 켤 때 기본값(2160)으로
                # 되돌아가므로 '제한 없음' 을 뜻하는 문자열로 명시해 둔다.
                lines.append('max_height = "best"   # 화질 제한 없음')
                continue
            if value is None:
                lines.append(f"# {field.name} = (설정 없음)")
                continue
            lines.append(f"{field.name} = {_toml_value(value)}")
        return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Path):
        return _toml_string(str(value))
    return _toml_string(str(value))


def _toml_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
