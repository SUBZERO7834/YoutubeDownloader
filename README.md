# YoutubeDownloader (4K)

YouTube 동영상을 **최대 4K(2160p) 화질로 내려받는 데스크톱 다운로더**입니다.

현재 상태: **M1 코어 엔진 + M2 CLI 동작** (GUI 는 M3 예정)

## 빠른 시작

```bash
pip install -e ".[dev]"        # 개발 설치
ytdl4k <URL>                   # 4K 이하 최고 화질로 받기
```

ffmpeg 이 필요합니다(4K 는 영상·음성이 분리되어 제공되므로 병합 필수).
설치돼 있지 않으면 경고를 띄우고 영상+음성이 한 파일인 포맷으로 자동 강등됩니다.

```bash
ytdl4k -F <URL>                        # 받을 수 있는 화질 목록 보기
ytdl4k -q 1080 -o ~/Videos <URL>       # 화질·저장 위치 지정
ytdl4k --codec efficiency <URL>        # AV1 우선 (같은 화질에 용량 ↓)
ytdl4k --container mp4 <URL>           # mp4 강제 (재인코딩 없이 담기는 스트림을 고름)
ytdl4k --audio-only <URL>              # 오디오만
ytdl4k --dry-run <URL>                 # 무엇을 받을지만 확인
ytdl4k --cookies-from-browser chrome <URL>   # 로그인이 필요한 영상
```

Ctrl+C 로 중단하면 받던 조각(`.part`)을 남겨 두고, 같은 명령을 다시 실행하면 이어받습니다.

## 문서

| 문서 | 내용 |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | 전체 개발 계획 · 마일스톤 · 일정 · 리스크 |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | 기능/비기능 요구사항 명세 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 아키텍처 · 모듈 설계 · 데이터 모델 |

## 개발

```bash
pytest -q                  # 전체 테스트
pytest -m "not integration"  # 실제 I/O 없이
ruff check . && ruff format --check .
```

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
