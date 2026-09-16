# 파일 지도

저장소에 있는 파일 48개가 각각 무슨 일을 하는지. (빌드 산출물·가상환경은 git 에 올리지 않는다)

의존 방향은 한 줄로 요약된다:

```
gui / cli  →  app  →  core  →  yt-dlp · ffmpeg
```

위쪽은 아래쪽을 알지만, 아래쪽은 위쪽을 모른다. `core` 는 화면이 있는지조차 모르고,
`app` 은 Qt 를 모른다. 이 방향이 깨지면 테스트가 어려워지므로 바꾸지 않는다.

---

## 1. 제품 코드 — `ytdl4k/`

### 진입점

| 파일 | 하는 일 |
| --- | --- |
| `__init__.py` | 버전 번호(`0.1.0`) 하나만 들고 있다 |
| `__main__.py` | `python -m ytdl4k` 로 명령줄을 띄운다 |
| `console.py` | 출력 인코딩 정리. 윈도우에서 결과를 파일로 넘길 때 한글·기호가 깨져 죽던 문제를 막는다 |

### `core/` — 도메인. 화면도 큐도 모른다

| 파일 | 하는 일 | 알아 둘 점 |
| --- | --- | --- |
| `models.py` | yt-dlp 의 헐거운 dict 를 `VideoInfo`·`VideoFormat` 으로 정규화. 코덱 패밀리 추출, HDR 판별, 용량 추정 | 열거형(`CodecPolicy`·`Container`·`ThumbnailMode`·`TaskState`)이 여기 모여 있다 |
| `formats.py` | **이 프로젝트의 심장.** 목표 화질·코덱·컨테이너 정책을 받아 어떤 스트림을 받을지 정한다 | 네트워크를 타지 않는 순수 함수라 고정 픽스처만으로 전부 테스트된다 |
| `extractor.py` | URL → `VideoInfo`. yt-dlp 를 얇게 감싼다 | yt-dlp 오류를 도메인 오류로 번역한다(로그인 필요/지역 제한/DRM/네트워크/후처리) |
| `downloader.py` | 실제 내려받기. 진행률 이벤트, 취소, 이어받기, 용량 확인, 결과 검증 | 표지를 넣을 수 있는 조합인지 판정하는 `embed_blocker()` 도 여기 있다 |
| `merger.py` | ffmpeg 찾기(번들 → PATH)와 결과 트랙 검증 | 실제 병합은 yt-dlp 가 ffmpeg 을 불러 한다. 여기서는 '소리 없는 4K 파일' 을 잡는 검증을 맡는다 |
| `errors.py` | 모든 오류를 **원인 + 사용자 메시지 + 다음 행동** 세 쪽으로 정규화 | UI 는 오류 종류를 몰라도 `message` 와 `hint` 만 띄우면 된다 |
| `__init__.py` | 위 모듈에서 바깥이 쓸 것들만 모아 내보낸다 | |

### `app/` — 유즈케이스. Qt 를 모른다

| 파일 | 하는 일 |
| --- | --- |
| `queue.py` | 동시 개수를 제한하는 다운로드 큐. 작업 상태(대기·받는 중·합치는 중·완료·실패·취소)를 관리하고 콜백으로 알린다 |
| `settings.py` | TOML 설정 읽기·쓰기. 파일이 깨져 있어도 기본값으로 뜬다 |
| `__init__.py` | 위 둘을 내보낸다 |

### `gui/` — PySide6 화면

| 파일 | 하는 일 |
| --- | --- |
| `main_window.py` | 주소 입력 → 화질·코덱·썸네일·로그인 선택 → 목록 순서의 창 하나 |
| `model.py` | 목록 표 모델과 진행률 막대 그리기 |
| `bridge.py` | 작업 스레드의 콜백을 Qt 시그널로 옮긴다. 위젯은 항상 메인 스레드에서만 건드려진다 |
| `app.py` | `QApplication` 구성, 클립보드 감시, `--smoke` 점검 경로 |
| `__init__.py` / `__main__.py` | `python -m ytdl4k.gui` 진입점 |

### `cli/`

| 파일 | 하는 일 |
| --- | --- |
| `main.py` | 인자 파싱, 화질 목록(`-F`), 진행률 표시, 자가 진단(`--self-check`), 첫 Ctrl+C 를 '이어받기 가능한 취소' 로 처리 |
| `__init__.py` | 빈 파일 (패키지 표시) |

### `resources/`

| 파일 | 하는 일 |
| --- | --- |
| `ffmpeg/.gitkeep` | 빌드할 때 여기에 ffmpeg 바이너리가 들어온다. 바이너리 자체는 git 에 올리지 않는다 |

---

## 2. 테스트 — `tests/` (162개)

| 파일 | 무엇을 지키는가 |
| --- | --- |
| `conftest.py` | 공용 픽스처 — 포맷 목록 JSON 을 `VideoInfo` 로 만들어 준다 |
| `fixtures/formats_4k.json` | 4K·8K·HDR·AV1·progressive 가 섞인 가짜 포맷 목록. **YouTube 없이 선택 로직 전부를 재현한다** |
| `test_formats.py` | 화질·코덱·컨테이너 선택 규칙 |
| `test_models.py` | 코덱 문자열 파싱, HDR 판별, 용량 추정 |
| `test_extractor.py` | yt-dlp 오류 → 도메인 오류 번역 |
| `test_downloader.py` | yt-dlp 옵션 구성, 진행률, 취소, 용량 확인, 결과 경로 찾기 |
| `test_merger.py` | ffmpeg 탐색과 결과 트랙 검증 |
| `test_thumbnail.py` | 표지를 넣을 수 있는 조합 판정과 막혔을 때의 강등 |
| `test_queue.py` | 큐의 상태 전이 — 실패가 큐 전체를 멈추지 않는지 포함 |
| `test_settings.py` | 설정 왕복. 깨진 파일에서도 뜨는지 |
| `test_cli.py` | 인자 해석, 진행률 표시, 오류 안내, 파이프 안전성 |
| `test_gui.py` | 위젯 동작. 화면 없는 환경(offscreen)에서 돈다 |
| `test_integration_local.py` | 로컬 HTTP 서버를 상대로 **실제로 바이트를 받아** 저장까지 확인 |
| `test_fetch_ffmpeg.py` | ffmpeg 확보 스크립트 |

---

## 3. 빌드·배포 — `scripts/`, `.github/`

| 파일 | 하는 일 |
| --- | --- |
| `scripts/fetch_ffmpeg.py` | static ffmpeg 확보(공식 빌드 / PyPI / 로컬 복사) + **컨테이너 왕복 건전성 검사**. `-version` 만 확인하면 특정 형식에서 죽는 빌드를 그대로 배포하게 된다 |
| `scripts/build.py` | PyInstaller 실행. 명령줄은 단일 파일, 창 화면은 폴더. 묶은 뒤 실제로 실행해 확인한다 |
| `scripts/pyi_entry.py` | 명령줄용 진입점. `__main__.py` 는 상대 임포트라 PyInstaller 진입점으로 쓰면 깨진다 |
| `scripts/pyi_entry_gui.py` | 창 화면용 진입점 (같은 이유) |
| `.github/workflows/ci.yml` | 푸시마다 린트·테스트. Ubuntu·Windows × Python 3.11/3.12 |
| `.github/workflows/release.yml` | 세 플랫폼 실행 파일 빌드. 맥·리눅스는 실행 권한을 지키려 tar.gz 로 묶는다 |

---

## 4. 설정·문서

| 파일 | 하는 일 |
| --- | --- |
| `pyproject.toml` | 패키지 정보, 의존성(yt-dlp·mutagen), 실행 명령(`ytdl4k`·`ytdl4k-gui`), ruff·pytest 설정 |
| `.gitignore` | 빌드 산출물·가상환경·**번들 ffmpeg**·받은 영상 파일을 git 에서 제외 |
| `README.md` | 개요, 내려받기·처음 실행하기, 사용법, 개발 방법 |
| `docs/PLAN.md` | 개발 계획, 마일스톤, 리스크, **계획과 달라진 결정과 그 이유** |
| `docs/REQUIREMENTS.md` | 기능·비기능 요구사항 (P0/P1/P2) |
| `docs/ARCHITECTURE.md` | 레이어 구조, 데이터 모델, 포맷 선택 로직, 구현 메모 |
| `docs/CODEMAP.md` | 이 문서 |
