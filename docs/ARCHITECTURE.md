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
    vcodec: str | None        # 'vp9' | 'av01...' | 'avc1...' | None(오디오 전용)
    acodec: str | None        # 'opus' | 'mp4a...' | None(영상 전용)
    width: int | None
    height: int | None        # 2160, 1440, ...
    fps: float | None
    hdr: bool
    filesize: int | None      # 없으면 filesize_approx
    tbr: float | None         # 총 비트레이트

    @property
    def is_video_only(self) -> bool: ...
    @property
    def is_audio_only(self) -> bool: ...

@dataclass(frozen=True)
class VideoInfo:
    id: str
    title: str
    duration: int             # 초
    uploader: str
    thumbnail_url: str
    formats: list[VideoFormat]
    is_live: bool
    has_drm: bool

@dataclass
class DownloadTask:
    url: str
    info: VideoInfo | None
    target: DownloadTarget     # 목표 화질/코덱/컨테이너 정책
    state: TaskState           # PENDING·EXTRACTING·DOWNLOADING·MERGING·DONE·FAILED·CANCELED
    progress: Progress         # percent, speed_bps, eta_s, stage
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
    cap = target.max_height                     # 예: 2160
    candidates = [f for f in videos if f.height <= cap]
    if not candidates:
        raise NoSuitableFormat(info, cap)       # "이 영상의 최고 화질은 ...입니다"
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
| avc1 / av01 | mp4a(AAC) | `.mp4` (그대로 remux) |
| vp9 | opus | `.webm` 또는 `.mkv` |
| vp9 / av01 | opus, 단 "MP4 강제" 옵션 | `.mp4` (opus → AAC 변환, 유일한 재인코딩 지점) |

기본값은 **무손실 우선**. 재인코딩은 사용자가 명시적으로 켤 때만.

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

## 7. 교체 가능성

`extractor`/`downloader`는 인터페이스로 감싸 yt-dlp에 직접 의존하지 않게 합니다.
이유는 두 가지: (1) 테스트에서 가짜 구현 주입, (2) 추후 엔진 교체·이중화 가능.
