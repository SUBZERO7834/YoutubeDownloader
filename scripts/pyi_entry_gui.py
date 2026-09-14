"""PyInstaller 전용 GUI 진입점 (절대 임포트만 쓴다)."""

import sys

from ytdl4k.gui.app import run

if __name__ == "__main__":
    sys.exit(run())
