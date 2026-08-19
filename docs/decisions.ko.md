# todoy — 결정 및 변경 기록

> English version: [decisions.md](decisions.md)

엔지니어링 결정과 주요 수정사항을 최신순으로 기록한다. 마일스톤마다 항목을 추가한다.

## M1 — 2026-08-20

### 결정

- **M1은 표준 라이브러리만 사용.** CLI는 `argparse` 기반, 서드파티 런타임 의존성 없음. 오버레이용 `pyobjc` optional extra가 초기에 추가됐으나 리뷰에서 제거 — M4에서 도입 예정.
- **데이터 모델.** `Todo`는 순수 dataclass(`text`, `done`, `id`, `source`), `to_dict`/`from_dict` 지원. 읽기 전용 소스에서는 `id`가 `None`이며, builtin 저장소만 id를 부여한다.
- **소스 플러그인 인터페이스.** `Source`는 ABC로, 필수 메서드는 오늘의 *미완료* 할 일을 반환하는 `get_todos() -> list[Todo]` 하나와 `name` 클래스 속성뿐. 관리 연산(`add`/`done`)은 인터페이스가 아니라 `BuiltinSource` 고유 기능이다.
- **builtin 저장소.** JSON 파일 경로는 `TODOY_DATA_FILE` 환경변수 → `$XDG_DATA_HOME/todoy/todos.json` → `~/.local/share/todoy/todos.json` 순으로 결정. 쓰기는 원자적(temp 파일 + `os.replace`). id는 재사용하지 않음(기존 최대 id + 1). 손상된 파일은 경로를 담은 `ValueError`를 발생시킨다.
- **CLI 에러 정책.** 예상 가능한 에러는 트레이스백을 노출하지 않는다: 없는 id, 손상된 데이터 파일 모두 stderr 메시지 + exit 1.

### 교차 리뷰 반영 수정

- CLI: 손상 파일 `ValueError`를 `main()`에서 잡아 stderr + exit 1로 보고, 회귀 테스트 추가 (기존: 트레이스백 노출).
- 패키징: 시기상조였던 `overlay = ["pyobjc"]` extra와 lockfile 항목 제거.
- 저장소 위생: 로컬 에이전트/세션 스캐폴딩(내부 기획 문서, 어시스턴트 설정)은 git-ignore 처리하고 공개 전 히스토리에서 제거. 저장소에 개인 경로 없음.

### 프로세스

- 마일스톤은 TDD로 진행하고, 머지 전 독립 리뷰어 2인의 교차 리뷰를 통과한다 (M1: 테스트 31개, ruff 통과).

## M2 — 2026-08-20

### 결정

- **Config.** `~/.config/todoy/config.toml` (우선순위: `TODOY_CONFIG_FILE` 환경변수 → `$XDG_CONFIG_HOME/todoy/config.toml` → `~/.config/todoy/config.toml`). 읽기는 표준 라이브러리 `tomllib`, 쓰기는 소형 수제 emitter (표준 라이브러리에 TOML writer가 없고, `tomli-w` 추가보다 의존성 최소화 우선).
- **마크다운 소스.** 파일의 mtime 날짜가 오늘이거나 config에 고정(pinned)된 파일이 할 일을 제공. 줄 규칙: `- [ ] 텍스트`와 `- 텍스트`는 미완료 할 일, `- [x]`는 제외; 텍스트 기준 중복 제거, 고정 파일 우선. 코드 펜스/YAML frontmatter는 아직 특별 처리하지 않음 (#10).
- **`add`/`done`은 항상 builtin 저장소 대상** — 어떤 소스가 켜져 있든 동일 (예측 가능한 UX); 읽기 전용 소스는 `list`(이후 TUI/오버레이)에서만 집계.
- **출력 새니타이즈를 #7에서 앞당김.** 마크다운 노트는 신뢰할 수 없는 입력이고 M2부터 터미널에 도달하므로, 렌더링되는 모든 할 일 텍스트에서 제어/이스케이프 문자를 제거.
- 개발 중 실제 Obsidian vault로 검증 (한국어 할 일, 중첩 폴더, 고정 노트) — vault 경로는 코드·테스트·픽스처에 넣지 않음.

### 교차 리뷰 반영 수정

- Config emitter: TOML 문자열에서 U+007F(DEL) 이스케이프 — 아니면 저장/로드 라운드트립이 깨져 todoy가 자기가 쓴 파일을 못 읽을 수 있었음.
- 미룬 Minor들은 이슈로 등록: 마크다운 파서 견고성(#10), CLI 하드닝 추가 항목(#6).

## M3 — 2026-08-20

### 결정

- **display 레이어 패키지.** TUI는 `src/todoy/display/`(`tui.py`, `messages.py`, `characters.py`)에 배치 — M4 오버레이 백엔드를 옆에 추가할 수 있는 구조. 공용 출력 새니타이저 `sanitize_text`도 여기로 이동.
- **약올리기 메시지 팩.** 영/한 풀(언어별 taunt ≥5, 뻔뻔한 축하 ≥3); 리뷰에서 톤 규칙 강제: 할 일/상황을 놀리되 사람을 공격하지 않는다. 언어 결정: 명시 플래그 → `TODOY_LANG` → `LANG`이 `ko`로 시작 → `en`. M3에서는 config 스키마 변경 없음.
- **캐릭터.** 내장 카탈로그(cat/dog/ghost/robot), 이모지 + 순수 ASCII 폴백 아트; `--character`로 선택, stdout 인코딩이 이모지를 못 다루면 자동 비활성(`--ascii`로 강제).
- **말풍선 크기는 표시 폭 기준** — 코드포인트 수가 아니라 동아시아 전각 문자를 2칸으로 계산(표준 라이브러리 `unicodedata.east_asian_width`), 한글도 정렬된 말풍선으로 렌더링.

### 교차 리뷰·보안 감사 반영 수정

- 습관적 실패를 암시하던 한국어 taunt 한 줄 교체(톤 규칙); 모든 taunt 줄이 `{count}`를 포함하는지 테스트로 강제.
- 마크다운 소스가 폴더 스캔 중 심볼릭 링크 파일을 읽지 않도록 수정(폴더 밖을 가리키는 링크가 파일 내용을 todo로 유출할 수 있었음); 고정(pinned) 노트는 예외(명시적 사용자 설정).
- CLI의 범용 에러 출력도 새니타이즈 — `--character` 에러 메시지가 제어 문자를 stderr에 반사하지 않음.

## M4 — 2026-08-20

### 결정

- **오버레이 아키텍처.** `display/overlay/`를 순수 파이썬 코어(`ReminderScheduler` monotonic 클록, `build_reminder_text`)와 얇은 pyobjc 백엔드(`macos.py`)로 분리, `OverlayBackend` 프로토콜 + `create_backend()` 팩토리 뒤에 배치 — 다른 OS 백엔드를 옆에 추가 가능; AppKit은 GUI 경로에서만 lazy import.
- **의존성.** `todoy[overlay]` extra = `pyobjc-framework-Cocoa`만 (전체 pyobjc 아님).
- **제품 규칙을 코드로 강제.** 말풍선 컨트롤은 정확히 둘 — 일시 스누즈와 종료. 영구 음소거 없음, "할 일 완료" 버튼 없음(의도적 마찰). 캐릭터는 화면 하단을 배회하고 실행 ~5초 후 첫 리마인드를 띄움.
- **Config.** 새 `[display]` 테이블: `character`, `character_image`(설정되고 읽을 수 있으면 이모지보다 사용자 이미지 우선), `snooze_minutes`. `todoy init`이 캐릭터와 선택적 이미지를 질문.
- **`todoy overlay --once`** — GUI 없이 리마인드 텍스트만 출력. 모든 OS에서 동작, 데모/테스트/CI용.
- **검증.** 자동 검증은 AppKit 창 상태와 정상 종료까지(`TODOY_OVERLAY_TEST_SECONDS`); 픽셀 스크린샷은 샌드박스 개발 환경(macOS TCC)에서 차단되어 최종 육안 확인은 수동 단계.

### 교차 리뷰 반영 수정

- macOS 백엔드가 모든 NSTimer를 저장하고 종료/테스트 타임아웃 시 invalidate (기존: 반복 실행 시 타이머 누수).
- 한글 전각 잘림 테스트와, `todoy.display.overlay` import가 AppKit을 끌어오지 않음을 검증하는 서브프로세스 테스트 추가.
- CLI `--once` 테스트가 가짜 모듈 대신 실제 overlay 코어를 사용 (통합 경계 검증).

## M1 이후 — 2026-08-20

- **LICENSE 파일을 M5보다 앞당겨 추가.** 사용자 요청으로 MIT `LICENSE` 파일(표준 원문, 저작권자 maengyo)을 M5를 기다리지 않고 지금 추가했다. `pyproject.toml`에는 이미 `license = "MIT"` (PEP 639 SPDX 표현식)이 있었고, LICENSE 파일 추가로 hatchling이 빌드 메타데이터에 `License-Expression: MIT` + `License-File: LICENSE`를 포함하게 됐다. `uv build`, `uv sync`, 전체 테스트 스위트(31개 통과, ruff 통과)로 검증했다.
- **의존성 라이선스 검토(license-compliance-expert).** 런타임 의존성 없음. dev 전용 의존성인 pytest(MIT), ruff(MIT)와 그 전이 의존성 colorama(BSD-3-Clause), iniconfig(MIT), packaging(Apache-2.0 OR BSD-2-Clause), pluggy(MIT), pygments(BSD-2-Clause) 모두 permissive 라이선스로 MIT 배포와 호환되며 copyleft 없음 — blocker 없음.
