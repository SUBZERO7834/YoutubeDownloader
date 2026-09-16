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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ytdl4k.console import configure_output  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FFMPEG_DIR = ROOT / "ytdl4k" / "resources" / "ffmpeg"
APP_NAME = "ytdl4k"
GUI_NAME = "ytdl4k-gui"

# 쓰지 않는데 자동으로 딸려 들어가 용량만 키우는 것들.
EXCLUDES = ["tkinter", "unittest", "pydoc", "doctest", "pytest", "test"]

# 명령줄판에서만 빼는 것. cli/main.py 의 launch_gui() 안에 PySide6 임포트가 있고
# PyInstaller 는 함수 안의 임포트까지 정적으로 따라가기 때문에, 빼 두지 않으면
# 창 화면을 쓰지도 않는 명령줄 실행 파일이 두 배로 커진다(43MB → 91MB).
# 실행 중에는 ImportError 를 잡아 "PySide6 가 필요합니다" 라고 안내한다.
CLI_ONLY_EXCLUDES = ["PySide6", "shiboken6"]


def bundled_binaries() -> list[Path]:
    if not FFMPEG_DIR.is_dir():
        return []
    return [p for p in sorted(FFMPEG_DIR.iterdir()) if p.is_file() and p.name != ".gitkeep"]


def build(onedir: bool = False, clean: bool = True, gui: bool = False) -> Path:
    """PyInstaller 실행.

    CLI 는 단일 파일, GUI 는 폴더로 묶는다. 창 앱을 단일 파일로 만들면 실행할 때마다
    200MB 가 넘는 내용을 통째로 풀기 때문에 뜨는 데 몇 초씩 걸린다.
    """
    binaries = bundled_binaries()
    if binaries:
        total = sum(p.stat().st_size for p in binaries) / 2**20
        print(f"· 함께 묶을 바이너리: {', '.join(p.name for p in binaries)} ({total:.0f}MB)")
        if not any(p.name.startswith("ffprobe") for p in binaries):
            print("! ffprobe 가 없습니다. 결과 트랙 검증과 mkv 표지 넣기가 빠진 채로 묶입니다.")
            print("  4K 기본 경로(vp9+opus)는 mkv 로 담기므로 표지 기능이 사실상 동작하지 않습니다.")
    else:
        print("! ytdl4k/resources/ffmpeg 가 비어 있습니다. 먼저 scripts/fetch_ffmpeg.py 를 실행하세요.")
        print("  (이대로 진행하면 시스템 ffmpeg 에 의존하는 실행 파일이 만들어집니다)")

    name = GUI_NAME if gui else APP_NAME
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir" if (onedir or gui) else "--onefile",
        # 창 앱에 콘솔이 따라붙으면 윈도우에서 검은 창이 같이 뜬다.
        "--windowed" if gui else "--console",
        "--name",
        name,
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
    ]
    if clean:
        cmd.append("--clean")
    for module in EXCLUDES + ([] if gui else CLI_ONLY_EXCLUDES):
        cmd += ["--exclude-module", module]
    for binary in binaries:
        # dest 는 core/merger.py 의 _bundle_dir() 가 찾는 경로와 일치해야 한다.
        cmd += ["--add-binary", f"{binary}{os.pathsep}resources/ffmpeg"]
    cmd += ["--paths", str(ROOT)]
    cmd.append(str(ROOT / "scripts" / ("pyi_entry_gui.py" if gui else "pyi_entry.py")))

    print("· PyInstaller 실행…")
    subprocess.run(cmd, check=True, cwd=ROOT)

    folder_build = onedir or gui
    produced = ROOT / "dist" / (Path(name) / name if folder_build else name)
    if os.name == "nt":
        produced = produced.with_suffix(".exe")
    if not produced.exists():
        raise SystemExit(f"✗ 결과물을 찾지 못했습니다: {produced}")
    print(f"✓ 완성: {produced}  ({produced.stat().st_size / 2**20:.0f}MB)")
    return produced


def smoke_test(binary: Path, gui: bool = False) -> None:
    """묶인 실행 파일이 정말 쓸 수 있는 상태인지 확인한다.

    ``--self-check`` 는 yt-dlp 임포트와 번들 ffmpeg 탐색을 둘 다 건드린다.
    묶인 실행 파일이 실패하는 경우는 대부분 이 둘이므로 여기서 잡힌다.
    """
    if gui:
        result = _run(binary, ["--smoke"])
        if result.returncode != 0:
            raise SystemExit(f"✗ 창이 뜨지 않았습니다 (종료코드 {result.returncode})\n{_output(result)}")
        print(_output(result) or "(출력 없음)")
        print("✓ 스모크 테스트 통과")
        return

    for args in (["--version"], ["--help"]):
        result = _run(binary, args)
        if result.returncode not in (0, 2):
            raise SystemExit(f"✗ 실행 실패: {args} (종료코드 {result.returncode})\n{_output(result)}")

    check = _run(binary, ["--self-check"])
    print(_output(check) or "(출력 없음)")
    if check.returncode != 0:
        raise SystemExit(f"✗ 자가 진단 실패 (종료코드 {check.returncode})")
    print("✓ 스모크 테스트 통과")


def _run(binary: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(binary), *args],
        capture_output=True,
        text=True,
        errors="replace",  # 실행 파일 출력의 인코딩 때문에 빌드가 죽지 않도록
        check=False,
    )


def _output(result: subprocess.CompletedProcess) -> str:
    """stdout·stderr 를 함께 본다. 플랫폼에 따라 한쪽이 비거나 None 일 수 있다."""
    return "\n".join(part.rstrip() for part in (result.stdout, result.stderr) if part).strip()


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gui", action="store_true", help="창 화면(PySide6) 실행 파일 만들기")
    parser.add_argument("--onedir", action="store_true", help="단일 파일 대신 폴더로 묶기 (시작이 빠름)")
    parser.add_argument("--no-clean", action="store_true", help="이전 빌드 캐시 재사용")
    parser.add_argument("--skip-smoke", action="store_true", help="빌드 후 실행 확인 생략")
    args = parser.parse_args(argv)

    if shutil.which("upx"):
        print("· upx 감지 — PyInstaller 가 자동으로 압축합니다")
    binary = build(onedir=args.onedir, clean=not args.no_clean, gui=args.gui)
    if not args.skip_smoke:
        smoke_test(binary, gui=args.gui)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
