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

## M7 (후속) — 2026-08-20

### 결정

- **메시지 깃발을 든 질주하는 말 (이슈 #12).** 캐릭터 `horse`(🐎) 카탈로그 추가; 이동 `gallop` = walk의 ~3배 속도 + 리드미컬한 더블비트 홉(≤14px). 메시지 표시가 독립 축이 됨: `message_style = "bubble"`(기본, 표시 시점 위치에 고정) vs `"flag"`(캐릭터에 붙어 함께 달리는 페넌트, 표시 중 매 틱 재배치, 화면 안으로 클램프). 등장 효과(`bubble_effect`)는 두 스타일 모두에 적용.
- 선택: `[display] message_style` + `todoy overlay --message-style {bubble,flag}`.

### 교차 리뷰 반영 수정

- shake 효과가 매 진동마다 재클램프(가장자리의 깃발이 화면 밖으로 밀릴 수 있었음)하고, 실시간 동행 좌표에 합성(질주 중 깃발이 순간 이탈할 수 있었음).
- bubble 모드는 배회 틱마다 재배치하지 않음 — 계약대로 표시 시점 위치 고정.

## M6 (후속) — 2026-08-20

### 결정

- **애니메이션 선택 (이슈 #11).** 캐릭터 이동 프리셋(`walk` 기본, `hop`, `float`, `dash`, `still`)은 `display/overlay/animations.py`의 순수·dt 구동·rng 주입형 상태머신(`CharacterMovement.step(dt) -> (x, y_offset)`)으로 구현하고, macOS 백엔드는 위치만 적용한다. 말풍선 등장 효과(`pop` 기본, `fade`, `slide`, `shake`, `none`)는 백엔드에서 `NSAnimationContext`로 적용.
- 선택 방법: config의 `[display] movement / bubble_effect` + `todoy overlay --movement/--bubble-effect` (플래그 > config > 기본값). `todoy init`은 의도적으로 확장하지 않음 — 마법사는 짧게 유지.
- 이름 검증은 `animations.validate_*`(오버레이 경로)에서, config 로드는 타입만 검사 — character 이름과 같은 분리. 알 수 없는 이름은 가능한 목록과 함께 새니타이즈된 stderr + exit 1.
- 캐릭터 위치 메모: 캐릭터는 하단 가장자리를 배회한다 — 화면 바닥에서 `CHARACTER_BOTTOM_MARGIN = 24px` 위 + 이동 애니메이션의 수직 오프셋(≤40px). 위치(edge) 설정화는 아직 요청되지 않은 후속 후보.

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

## M5 — 2026-08-20

### 결정

- **CI: 3-OS 매트릭스.** `.github/workflows/ci.yml`이 ubuntu-latest/macos-latest/windows-latest × Python 3.11/3.13(fail-fast: false)에서 `uv sync --dev`, `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`를 실행한다. `pyobjc`는 macOS에서만 빌드되므로, `overlay` extra 동기화와 import 검증(`import todoy.display.overlay.base`)은 `runner.os == 'macOS'`일 때만 수행한다 — 다른 백엔드는 어디서든 순수 파이썬으로 import 가능한 상태를 유지한다. `PYTHONIOENCODING: utf-8`은 Windows뿐 아니라 모든 OS의 job 레벨에 설정했다 — todoy가 이모지와 한글 텍스트를 출력하고, Windows 콘솔 코드페이지가 기본적으로 UTF-8이 아니기 때문이다.
- **릴리스: 태그 트리거 Trusted Publishing.** `.github/workflows/release.yml`은 `v*` 태그에서 트리거되며 세 job으로 구성된다 — `build`(uv build → sdist+wheel → upload-artifact), `publish`(download-artifact → `pypa/gh-action-pypi-publish`로 PyPI **Trusted Publishing**(OIDC) 사용 — 저장소에 API 토큰/시크릿을 저장하지 않음), `release`(download-artifact → `softprops/action-gh-release`로 빌드 산출물을 GitHub Release에 첨부). `permissions:`는 job별로 최소화 — `publish`에만 `id-token: write`, `release`에만 `contents: write`; 최상위 기본값은 `contents: read`. Trusted Publishing은 첫 태그 푸시 전에 PyPI 프로젝트 페이지에 "pypi" trusted publisher를 설정해야 하는데, 이는 이 저장소에서 자동화할 수 없는 외부/계정 작업으로 유지관리자에게 남겨둔다.
- **공급망 하드닝.** 서드파티 GitHub Action(`actions/checkout`, `astral-sh/setup-uv`, `actions/upload-artifact`, `actions/download-artifact`, `pypa/gh-action-pypi-publish`, `softprops/action-gh-release`) 전부를 전체 커밋 SHA로 고정하고 `# vX.Y.Z` 주석을 달았다 — 작성 시점에 각 저장소 GitHub API의 태그 ref에서 직접 조회한 값이며, 가변적인 태그가 아니다. 모든 `actions/checkout` 단계는 `persist-credentials: false`도 설정해, 체크아웃 이후 실행되는 무엇에도 기본 `GITHUB_TOKEN`이 git config에 남지 않도록 했다.
- **패키징 메타데이터.** `pyproject.toml`에 `authors`(이메일 없이 이름만), `keywords`, PyPI `classifiers`(Beta/Console/Developers+End Users/OS Independent/Python 3.11–3.13/Office-Business-Scheduling)를 추가했다 — 단, 폐지된 `License :: OSI Approved :: MIT License` classifier는 의도적으로 제외했다. PEP 639의 SPDX `license = "MIT"` 필드가 이제 단일 근거이고, hatchling이 이미 그로부터 `License-Expression: MIT`를 생성하기 때문이다. `[project.urls]`(Homepage/Repository/Issues → `https://github.com/maengyo/todoy`)도 추가했다.
- **데모 자산.** `demo/demo.tape`(VHS 스크립트)와 `docs/demo.md`/`docs/demo.ko.md`(녹화 안내 문서)를 작성했지만, GIF 자체(`demo/todoy.gif`, `demo/overlay.gif`)는 녹화되지 않았다 — 이 환경에는 vhs/asciinema/화면 녹화 도구가 없다. README의 데모 섹션은 이를 실제 `![...]()` 태그가 아니라 주석 처리된 `<!-- ![...] -->` placeholder로 삽입해, 녹화·커밋되기 전까지 아무것도 404가 뜨지 않도록 했다.
- **overlay extra 의존성 라이선스 검토.** `todoy[overlay]`의 유일한 의존성인 `pyobjc-framework-Cocoa`(그리고 이를 끌어오는 `pyobjc-core`)는 MIT 라이선스다 — `uv sync --dev --extra overlay` 후 두 패키지의 설치된 wheel `METADATA`를 직접 확인해 검증했다(둘 다 `License: MIT`, `pyobjc-framework-Cocoa`는 `License-File: LICENSE.txt`도 포함). todoy의 MIT 라이선스와 완전히 호환되며 blocker 없음.

### 검증

`uv run pytest -q`(186개 통과), `uv run ruff check .` + `uv run ruff format --check .`(클린), `uv build`(sdist+wheel 빌드, wheel `METADATA`를 직접 확인해 `License-Expression: MIT`와 classifier 목록 검증), `uv run python -c "import todoy"`, 그리고 두 워크플로 YAML 파일을 `pyyaml`로 파싱해 검증했다(프로젝트 의존성으로 추가하지 않고 `uv run --with pyyaml`로 일회성 설치). CI의 각 job 단계가 실행할 명령(`uv sync --dev`, `uv sync --dev --extra overlay`, overlay import 체크)도 이 머신에서 직접 손으로 먼저 실행해 `ci.yml`에 커밋하기 전에 동작을 확인했다; 워크플로 자체를 실제 GitHub Actions 러너로 실행하지는 못했다.
