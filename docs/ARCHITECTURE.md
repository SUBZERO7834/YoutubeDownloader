# 아키텍처 설계 초안

- 문서 상태: **초안 (v0.1)**

## 1. 레이어 구조

핵심 원칙: **코어는 UI를 모른다.** CLI와 GUI는 같은 코어를 쓰는 두 개의 껍데기.

```
┌─────────────────┐   ┌─────────────────┐
│   GUI (PySide6) │   │   CLI (argparse)│
└────────┬────────┘   └────────┬────────┘
         └──────────┬──────────┘
                    ▼
         ┌──────────────────────┐
         │  app/ (유즈케이스)    │  큐 관리, 설정, 이벤트 버스
         └──────────┬───────────┘
                    ▼
         ┌──────────────────────┐
         │  core/ (도메인)       │  추출 · 포맷선택 · 다운로드 · 병합
         └──────────┬───────────┘
                    ▼
         ┌──────────────────────┐
         │  yt-dlp   │   ffmpeg  │  외부 의존성 (교체 가능하게 래핑)
         └──────────────────────┘
```

## 2. 디렉터리(예정)

```
ytdl4k/
├── core/
│   ├── extractor.py       # yt-dlp 래퍼: URL → VideoInfo
│   ├── formats.py         # VideoFormat 모델 + 포맷 선택 로직
│   ├── downloader.py      # 다운로드 실행 + 진행률 이벤트
│   ├── merger.py          # ffmpeg remux/변환
│   ├── postprocess.py     # 자막·썸네일·메타데이터
│   └── errors.py          # 도메인 예외 (사용자 메시지 포함)
├── app/
│   ├── queue.py           # 다운로드 큐, 동시성 제어
│   ├── settings.py        # config.toml 로드/저장
│   └── events.py          # 진행률/상태 이벤트 정의
├── cli/__main__.py
├── gui/
│   ├── main_window.py
│   ├── queue_view.py
│   └── settings_dialog.py
└── resources/ffmpeg/      # 번들 바이너리 (플랫폼별)
tests/
docs/
```

## 3. 데이터 모델 (초안)

```python
@dataclass(frozen=True)
class VideoFormat:
    format_id: str
    ext: str
    vcodec: str | None  # 'vp9' | 'av01...' | 'avc1...' | None(오디오 전용)
    acodec: str | None  # 'opus' | 'mp4a...' | None(영상 전용)
    width: int | None
    height: int | None  # 2160, 1440, ...
    fps: float | None
    hdr: bool
    filesize: int | None  # 없으면 filesize_approx
    tbr: float | None  # 총 비트레이트

    @property
    def is_video_only(self) -> bool: ...
    @property
    def is_audio_only(self) -> bool: ...


@dataclass(frozen=True)
class VideoInfo:
    id: str
    title: str
    duration: int  # 초
    uploader: str
    thumbnail_url: str
    formats: list[VideoFormat]
    is_live: bool
    has_drm: bool


@dataclass
class DownloadTask:
    url: str
    info: VideoInfo | None
    target: DownloadTarget  # 목표 화질/코덱/컨테이너 정책
    state: TaskState  # PENDING·EXTRACTING·DOWNLOADING·MERGING·DONE·FAILED·CANCELED
    progress: Progress  # percent, speed_bps, eta_s, stage
    output_path: Path | None
    error: AppError | None
```

## 4. 핵심 흐름

```
URL
 └─ extractor.extract(url)            → VideoInfo
     └─ formats.select(info, target)  → (video_fmt, audio_fmt) 또는 (combined_fmt,)
         └─ downloader.run(...)       → 진행률 이벤트 스트림 → .part 파일들
             └─ merger.remux(...)     → 최종 파일 1개
                 └─ postprocess(...)  → 자막/썸네일/메타데이터
```

### 포맷 선택 로직 (의사 코드)

```python
def select(info, target) -> Selection:
    videos = [f for f in info.formats if f.is_video_only and f.height]
    audios = [f for f in info.formats if f.is_audio_only]

    # 1) 목표 해상도 이하에서 가장 높은 해상도
    cap = target.max_height  # 예: 2160
    candidates = [f for f in videos if f.height <= cap]
    if not candidates:
        raise NoSuitableFormat(info, cap)  # "이 영상의 최고 화질은 ...입니다"
    best_h = max(f.height for f in candidates)

    # 2) 같은 해상도 안에서 코덱 선호도 → fps → 비트레이트 순
    same = [f for f in candidates if f.height == best_h]
    video = max(same, key=lambda f: (target.codec_rank(f.vcodec), f.fps or 0, f.tbr or 0))

    # 3) 오디오는 코덱 선호도 + 비트레이트
    audio = max(audios, key=lambda f: (target.audio_rank(f.acodec), f.tbr or 0))
    return Selection(video, audio, container=pick_container(video, audio, target))
```

이 함수는 **네트워크를 타지 않으므로 고정된 JSON 픽스처로 완전히 단위 테스트 가능**합니다.
YouTube 사양이 바뀌어도 이 로직의 테스트는 계속 유효합니다.

### 컨테이너 결정

| 영상 | 음성 | 결과 |
| --- | --- | --- |
| avc1 / av01 | mp4a(AAC) | `.mp4` |
| vp9 / av01 | opus | `.webm` |
| 섞인 조합 (예: avc1 + opus) | | `.mkv` — 제약이 사실상 없는 마지막 안전망 |
| "MP4 강제" 옵션 | | `.mp4` + **mp4 친화 스트림을 선택** |

**재인코딩은 어디에도 없다.** 초안에는 mp4 강제 시 opus → AAC 변환을 두었으나,
YouTube 가 어차피 AAC(`140`) 트랙을 함께 제공하므로 *변환 대신 선택*으로 해결했다.

ffmpeg 7.x 는 vp9+opus 를 mp4 에 담는 것도 허용하므로, `_MP4_SAFE_*` 목록은
'먹싱 가능 여부' 가 아니라 **플레이어 호환성** 기준이다 (실제 ffmpeg 으로 6개 조합 확인).

## 5. 동시성 모델

- 다운로드 작업은 **워커 풀**(기본 3)에서 실행. GUI 스레드는 절대 블로킹하지 않음.
- 진행률은 yt-dlp의 `progress_hooks` → 이벤트 큐 → UI가 200ms 주기로 폴링(이벤트 폭주 방지).
- ffmpeg은 `subprocess`로 실행하고 stderr를 파싱해 병합 진행률 산출.
- 취소는 협조적 취소(cancel flag 확인 + 프로세스 종료), `.part` 파일은 보존해 이어받기에 사용.

## 6. 오류 처리 설계

모든 예외는 `AppError`로 정규화하고 **(원인, 사용자 메시지, 다음 행동)** 세 필드를 갖습니다.

| 상황 | 사용자에게 보이는 메시지 예 |
| --- | --- |
| 4K 없음 | "이 영상은 최대 1080p까지 제공됩니다. 1080p로 받을까요?" |
| 연령/로그인 제한 | "로그인이 필요한 영상입니다. 설정에서 브라우저 쿠키를 연결해 주세요." |
| 추출 실패(사양 변경 추정) | "YouTube 변경으로 추출에 실패했습니다. 업데이트를 확인해 주세요." + 업데이트 버튼 |
| 디스크 부족 | "예상 용량 8.2GB, 남은 공간 3.1GB입니다." |
| DRM | "보호된 콘텐츠는 지원하지 않습니다." |

## 7. 구현 메모 (v0.1)

- **병합 주체**: 실제 remux 는 yt-dlp 가 ffmpeg 을 불러 수행한다. `merger.py` 는
  ① ffmpeg 탐색(번들 → PATH) ② 결과 트랙 검증 ③ 단독 remux 유틸 담당.
  검증을 따로 둔 이유는 '영상은 있는데 소리가 없는 4K 파일' 이 조용히 나오는 사고를 막기 위해서다.
- **최종 파일 경로**: 병합 후 확장자가 바뀌므로 템플릿으로 추측하면 틀린다.
  yt-dlp 결과의 `requested_downloads[*].filepath` 를 정답으로 쓰고, 없을 때만 glob 으로 되돌아간다.
- **취소**: 진행률 훅에서 내부 신호 예외를 던져 yt-dlp 콜스택을 빠져나온다.
  `.part` 는 지우지 않으므로 같은 명령을 다시 실행하면 이어받는다.
- **ffmpeg 없음**: 실패시키지 않고 `select(..., can_merge=False)` 로 progressive 포맷만
  후보에 남긴다. 4K 는 불가능해지지만(그런 포맷이 없다) 받을 수 있는 것은 받게 한다.
- **번들 경로**: PyInstaller 로 묶이면 리소스는 소스 트리가 아니라 실행 시 풀리는
  `sys._MEIPASS` 아래에 놓인다. `merger._bundle_dir()` 가 이 차이를 흡수하므로
  나머지 코드는 개발 실행인지 실행 파일인지 몰라도 된다.
- **진입점**: `ytdl4k/__main__.py` 는 상대 임포트를 쓰므로 PyInstaller 진입 스크립트로
  쓸 수 없다(최상위 스크립트로 실행되어 상대 임포트가 깨진다). `scripts/pyi_entry.py`
  라는 절대 임포트 전용 진입점을 따로 둔다.

## 8. 교체 가능성

`extractor`/`downloader`는 인터페이스로 감싸 yt-dlp에 직접 의존하지 않게 합니다.
이유는 두 가지: (1) 테스트에서 가짜 구현 주입, (2) 추후 엔진 교체·이중화 가능.
