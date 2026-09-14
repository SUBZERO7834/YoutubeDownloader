"""PyInstaller 전용 진입점.

``ytdl4k/__main__.py`` 는 상대 임포트(``from .cli.main import main``)를 쓰는데,
PyInstaller 는 진입 스크립트를 패키지가 아닌 최상위 스크립트로 실행하므로
상대 임포트가 깨진다. 그래서 절대 임포트만 쓰는 얇은 진입점을 따로 둔다.
"""

import sys

from ytdl4k.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
