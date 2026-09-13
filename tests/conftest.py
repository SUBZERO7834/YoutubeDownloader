import json
from pathlib import Path

import pytest

from ytdl4k.core.models import VideoInfo

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_4k() -> dict:
    return json.loads((FIXTURES / "formats_4k.json").read_text(encoding="utf-8"))


@pytest.fixture
def info_4k(raw_4k) -> VideoInfo:
    return VideoInfo.from_ytdlp(raw_4k)
