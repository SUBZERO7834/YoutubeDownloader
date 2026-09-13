"""로컬 HTTP 서버를 상대로 한 실제 다운로드 경로 검증.

외부 네트워크도 ffmpeg 도 필요 없다. yt-dlp 의 generic 추출기가 직접 링크로
인식하도록 ``video/mp4`` 로 응답하는 서버를 띄우고, 우리 Downloader 가
정말로 바이트를 받아 올바른 경로에 저장하는지, 진행률 이벤트가 흐르는지를 본다.

``-m "not integration"`` 으로 제외할 수 있다.
"""

from __future__ import annotations

import contextlib
import http.server
import socketserver
import threading

import pytest

from ytdl4k.core.downloader import Downloader
from ytdl4k.core.extractor import YtDlpExtractor
from ytdl4k.core.formats import Selection
from ytdl4k.core.models import TaskState

pytestmark = pytest.mark.integration

PAYLOAD = bytes(range(256)) * 4096  # 1MiB


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self._head()

    def do_GET(self):
        start = self._range_start()
        body = PAYLOAD[start:]
        self._head(length=len(body), partial=start > 0)
        # yt-dlp 는 크기만 확인하고 연결을 끊기도 한다
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def _head(self, length: int = len(PAYLOAD), partial: bool = False):
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def _range_start(self) -> int:
        header = self.headers.get("Range", "")
        return int(header.split("=")[1].split("-")[0]) if header.startswith("bytes=") else 0

    def log_message(self, *args):
        pass


@pytest.fixture
def media_server():
    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/sample.mp4"
    server.shutdown()
    server.server_close()


def test_downloads_bytes_and_reports_progress(media_server, tmp_path):
    extractor = YtDlpExtractor()
    info = extractor.extract(media_server)
    assert info.formats, "generic 추출기가 포맷을 하나도 주지 않았습니다"

    events = []
    downloader = Downloader(
        output_dir=tmp_path,
        base_options=extractor.base_options(),
        on_progress=events.append,
        overwrite=True,
    )
    selection = Selection(video=info.formats[0], audio=None, container="mp4")
    path = downloader.download(info, selection)

    assert path.exists()
    assert path.read_bytes() == PAYLOAD  # 받은 내용이 원본과 정확히 같다
    assert path.parent == tmp_path  # outtmpl 이 지정한 폴더에 저장됐다
    stages = [e.stage for e in events]
    assert TaskState.DOWNLOADING in stages and stages[-1] is TaskState.DONE
    assert max(e.percent for e in events) == 100.0
