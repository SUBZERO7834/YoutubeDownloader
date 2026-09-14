"""콘솔 출력 인코딩 정리.

윈도우에서 출력이 **리다이렉트**되면(파이프·파일·CI 로그) 파이썬은 콘솔이 아니라
로케일 인코딩(cp949·cp1252)으로 인코딩한다. 한글이나 ✓ 같은 기호가 거기에 없으면
UnicodeEncodeError 로 프로그램이 죽는다 — 실제로 CI 윈도우 러너에서 그렇게 죽었다.

콘솔에 직접 쓸 때는 파이썬이 WriteConsoleW 를 쓰므로 인코딩과 무관하다.
그래서 리다이렉트된 경우에만 UTF-8 로 바꾸고, 어느 경우든 errors="replace" 를 걸어
인코딩 때문에 죽는 일이 없게 한다.
"""

from __future__ import annotations

import contextlib
import sys
from typing import TextIO


def configure_output(*streams: TextIO) -> None:
    for stream in streams or (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        is_console = bool(getattr(stream, "isatty", lambda: False)())
        with contextlib.suppress(Exception):
            if is_console:
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
