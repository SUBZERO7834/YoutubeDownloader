#!/usr/bin/env python3
"""PyInstaller 로 단일 실행 파일을 만든다.

    python scripts/fetch_ffmpeg.py      # 먼저 ffmpeg 을 리소스에 채우고
    python scripts/build.py             # 묶는다 → dist/ytdl4k

ffmpeg 이 리소스에 없으면 경고만 하고 계속 진행한다. 그렇게 만든 실행 파일은
시스템에 설치된 ffmpeg 을 찾아 쓰고, 그것도 없으면 progressive 포맷으로 강등된다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FFMPEG_DIR = ROOT / "ytdl4k" / "resources" / "ffmpeg"
APP_NAME = "ytdl4k"

# 쓰지 않는데 자동으로 딸려 들어가 용량만 키우는 것들.
EXCLUDES = ["tkinter", "unittest", "pydoc", "doctest", "pytest", "test"]


def bundled_binaries() -> list[Path]:
    if not FFMPEG_DIR.is_dir():
        return []
    return [p for p in sorted(FFMPEG_DIR.iterdir()) if p.is_file() and p.name != ".gitkeep"]


def build(onedir: bool = False, clean: bool = True) -> Path:
    binaries = bundled_binaries()
    if binaries:
        total = sum(p.stat().st_size for p in binaries) / 2**20
        print(f"· 함께 묶을 바이너리: {', '.join(p.name for p in binaries)} ({total:.0f}MB)")
    else:
        print("! ytdl4k/resources/ffmpeg 가 비어 있습니다. 먼저 scripts/fetch_ffmpeg.py 를 실행하세요.")
        print("  (이대로 진행하면 시스템 ffmpeg 에 의존하는 실행 파일이 만들어집니다)")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir" if onedir else "--onefile",
        "--console",
        "--name",
        APP_NAME,
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
    ]
    if clean:
        cmd.append("--clean")
    for module in EXCLUDES:
        cmd += ["--exclude-module", module]
    for binary in binaries:
        # dest 는 core/merger.py 의 _bundle_dir() 가 찾는 경로와 일치해야 한다.
        cmd += ["--add-binary", f"{binary}{os.pathsep}resources/ffmpeg"]
    cmd += ["--paths", str(ROOT)]
    cmd.append(str(ROOT / "scripts" / "pyi_entry.py"))

    print("· PyInstaller 실행…")
    subprocess.run(cmd, check=True, cwd=ROOT)

    produced = ROOT / "dist" / (APP_NAME if not onedir else Path(APP_NAME) / APP_NAME)
    if os.name == "nt":
        produced = produced.with_suffix(".exe")
    if not produced.exists():
        raise SystemExit(f"✗ 결과물을 찾지 못했습니다: {produced}")
    print(f"✓ 완성: {produced}  ({produced.stat().st_size / 2**20:.0f}MB)")
    return produced


def smoke_test(binary: Path) -> None:
    """묶인 실행 파일이 정말 쓸 수 있는 상태인지 확인한다.

    ``--self-check`` 는 yt-dlp 임포트와 번들 ffmpeg 탐색을 둘 다 건드린다.
    묶인 실행 파일이 실패하는 경우는 대부분 이 둘이므로 여기서 잡힌다.
    """
    for args in (["--version"], ["--help"]):
        result = subprocess.run([str(binary), *args], capture_output=True, text=True, check=False)
        if result.returncode not in (0, 2):
            raise SystemExit(f"✗ 실행 실패: {args}\n{result.stdout}\n{result.stderr}")

    check = subprocess.run([str(binary), "--self-check"], capture_output=True, text=True, check=False)
    print(check.stdout.rstrip())
    if check.returncode != 0:
        raise SystemExit(f"✗ 자가 진단 실패\n{check.stderr}")
    print("✓ 스모크 테스트 통과")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onedir", action="store_true", help="단일 파일 대신 폴더로 묶기 (시작이 빠름)")
    parser.add_argument("--no-clean", action="store_true", help="이전 빌드 캐시 재사용")
    parser.add_argument("--skip-smoke", action="store_true", help="빌드 후 실행 확인 생략")
    args = parser.parse_args(argv)

    if shutil.which("upx"):
        print("· upx 감지 — PyInstaller 가 자동으로 압축합니다")
    binary = build(onedir=args.onedir, clean=not args.no_clean)
    if not args.skip_smoke:
        smoke_test(binary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
