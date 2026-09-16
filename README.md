# YoutubeDownloader (4K)

YouTube 동영상을 **최대 4K(2160p) 화질로 내려받는 데스크톱 다운로더**입니다.

현재 상태: **창 화면(GUI)까지 동작** — M1 코어 · M2 CLI · M3 GUI · M5 패키징

## 실행 파일 받기

빌드된 실행 파일은 GitHub Actions 에서 받습니다 — 저장소의 **Actions → 실행 파일 빌드**
→ 최근 실행 → Artifacts 에 세 가지가 올라옵니다.

| 파일 | 플랫폼 | 형태 |
| --- | --- | --- |
| `ytdl4k-gui-windows-x86_64` | Windows 10+ | 창 화면 (폴더, 압축 해제 후 실행) |
| `ytdl4k-gui-macos-arm64` | macOS (Apple Silicon) | 창 화면 |
| `ytdl4k-gui-linux-x86_64` | Linux | 창 화면 |
| `ytdl4k-windows-x86_64.exe` | Windows 10+ | 명령줄 (단일 파일) |
| `ytdl4k-macos-arm64` | macOS (Apple Silicon) | 명령줄 |
| `ytdl4k-linux-x86_64` | Linux | 명령줄 |

### 처음 실행하기

1. 위 링크에서 원하는 파일을 내려받습니다(아티팩트 다운로드에는 GitHub 로그인이 필요합니다).
   받아지는 것은 `.zip` 이고, 맥·리눅스용은 그 안에 `.tar.gz` 가 한 번 더 들어 있습니다.
   GitHub 아티팩트 zip 은 유닉스 실행 권한을 보존하지 못해서, 권한을 지키려고 한 번 더 묶은 것입니다.
   `tar -xzf ytdl4k-gui-macos-arm64.tar.gz` 로 푸시면 바로 실행됩니다.
2. **폴더째 압축을 풉니다.** 창 화면판은 실행 파일 옆의 `_internal` 폴더가 있어야 뜹니다 —
   `ytdl4k-gui.exe` 만 따로 꺼내면 실행되지 않습니다.
3. 폴더 안의 `ytdl4k-gui`(윈도우는 `ytdl4k-gui.exe`)를 실행합니다.

처음 실행할 때 운영체제가 경고를 띄웁니다. 제작자 서명(코드 서명)을 아직 넣지 않았기 때문입니다.

| 운영체제 | 넘어가는 방법 |
| --- | --- |
| 윈도우 | "Windows의 PC 보호" → **추가 정보** → **실행** |
| macOS | 파일을 **우클릭 → 열기** → **열기** (더블클릭으로는 막힙니다) |
| 리눅스 | 터미널에서 `chmod +x ytdl4k-gui` 한 번 |

창이 뜨면 맨 아래 상태줄에 `준비됨 · 합치기 도구: …` 이라고 나옵니다. 여기까지 나오면
4K 를 받을 준비가 된 것입니다. `ffmpeg 없음` 이라고 나오면 압축이 제대로 풀리지 않은 것입니다.

창 화면이 폴더째 묶여 있는 이유는, 단일 파일로 만들면 실행할 때마다 200MB 가 넘는 내용을
푸느라 뜨는 데 몇 초씩 걸리기 때문입니다.

Python 도 ffmpeg 도 따로 설치할 필요가 없습니다 — 하나의 파일에 다 들어 있습니다.
받은 뒤 제대로 준비됐는지 확인하려면:

```
ytdl4k --self-check
```

macOS/Linux 에서는 첫 실행 전에 `chmod +x ytdl4k` 가 필요합니다.

## 빠른 시작

```bash
pip install -e ".[gui]"        # 창 화면까지 설치
ytdl4k-gui                     # 창 화면 실행 (ytdl4k --gui 도 같다)
ytdl4k <URL>                   # 명령줄로 4K 이하 최고 화질 받기
```

### 창 화면

주소를 붙여넣고 화질을 고른 뒤 `받기` 를 누르면 목록에 쌓이고 동시에 처리됩니다.
복사해 온 유튜브 주소는 입력칸에 자동으로 채워집니다(받기 시작하지는 않습니다).
연령 제한 영상은 `로그인` 에서 로그인된 브라우저를 고르면 됩니다.
`썸네일` 을 "영상에 넣기" 로 두면 플레이어와 파일 탐색기에서 표지로 보입니다.
설정(화질·저장 위치 등)은 창을 닫을 때 저장되어 다음에 켤 때 그대로 돌아옵니다.

ffmpeg 이 필요합니다(4K 는 영상·음성이 분리되어 제공되므로 병합 필수).
설치돼 있지 않으면 경고를 띄우고 영상+음성이 한 파일인 포맷으로 자동 강등됩니다.

```bash
ytdl4k -F <URL>                        # 받을 수 있는 화질 목록 보기
ytdl4k -q 1080 -o ~/Videos <URL>       # 화질·저장 위치 지정
ytdl4k --codec efficiency <URL>        # AV1 우선 (같은 화질에 용량 ↓)
ytdl4k --container mp4 <URL>           # mp4 강제 (재인코딩 없이 담기는 스트림을 고름)
ytdl4k --audio-only <URL>              # 오디오만
ytdl4k --thumbnail embed <URL>         # 썸네일을 영상 안에 표지로 넣기
ytdl4k --thumbnail file <URL>          # 썸네일을 그림 파일로 따로 저장
ytdl4k --dry-run <URL>                 # 무엇을 받을지만 확인
ytdl4k --cookies-from-browser chrome <URL>   # 로그인이 필요한 영상
```

Ctrl+C 로 중단하면 받던 조각(`.part`)을 남겨 두고, 같은 명령을 다시 실행하면 이어받습니다.

### 썸네일에 대해 알아 둘 것

webm 컨테이너에는 표지를 넣을 수 없습니다(yt-dlp 제약). 그래서 표지를 넣기로 하면
4K 기본 조합(VP9+Opus)은 **mkv** 로 담깁니다 — 같은 스트림을 다른 그릇에 담는 것이라
화질·음질 손실은 없습니다. 오디오만 받을 때는 같은 이유로 Opus 대신 AAC(m4a)를 고릅니다.

넣을 수 없는 상황(ffprobe 없음 등)에서는 **실패시키지 않고** 그림 파일로 따로 저장하고
그 이유를 화면에 알려 줍니다. `ytdl4k --self-check` 로 지금 무엇이 가능한지 볼 수 있습니다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | 전체 개발 계획 · 마일스톤 · 일정 · 리스크 |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 기능/비기능 요구사항 명세 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 아키텍처 · 모듈 설계 · 데이터 모델 |

## 개발

```bash
pytest -q                    # 전체 테스트
pytest -m "not integration"  # 실제 I/O 없이
ruff check . && ruff format --check .
```

### 직접 빌드하기

```bash
python scripts/fetch_ffmpeg.py     # static ffmpeg 을 리소스에 채운다
python scripts/build.py            # → dist/ytdl4k (약 43MB, 단일 파일)
```

`fetch_ffmpeg.py` 는 받은 ffmpeg 으로 mp4/webm/mkv/ts **왕복 먹싱·디먹싱 검사**를 돌린다.
`-version` 만 확인하면 특정 컨테이너에서 죽는 빌드를 그대로 배포하게 되기 때문이다
(실제로 PyPI 경유 static 빌드 7.0.2 는 MPEG-TS 입력에서 세그폴트한다).

PyPI 만 열린 환경에서는 `--from-pypi`, 이미 받아 둔 바이너리가 있으면 `--from-path DIR` 을 쓴다.

포맷 선택 로직은 네트워크를 타지 않는 순수 함수라 고정 픽스처(`tests/fixtures/formats_4k.json`)만으로
전부 검증됩니다. YouTube 사양이 바뀌어도 이 테스트는 계속 유효합니다.

## 한 줄 요약

`yt-dlp`(스트림 추출) + `ffmpeg`(영상·음성 병합)을 코어로 두고,
그 위에 CLI → GUI 순서로 쌓아 올리는 구조입니다.
YouTube는 1080p를 넘는 화질을 **영상 전용 / 음성 전용 스트림으로 분리(DASH)** 해서 제공하므로,
4K 다운로드의 본질은 "두 스트림을 받아서 합치는 것"입니다.

## 이용 시 유의사항

- 이 도구는 **본인이 업로드한 영상, 저작권자가 다운로드를 허용한 영상, 공정이용 범위의 개인적 이용**을 전제로 합니다.
- YouTube 서비스 약관은 별도 허가 없는 다운로드를 제한합니다. 이용자 책임 하에 각국 법률과 약관을 확인하고 사용하세요.
- DRM이 적용된 콘텐츠(영화 대여/구매 등)는 지원 대상이 아니며, 우회 기능도 구현하지 않습니다.
