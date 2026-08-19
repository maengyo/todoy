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

## M1 이후 — 2026-08-20

- **LICENSE 파일을 M5보다 앞당겨 추가.** 사용자 요청으로 MIT `LICENSE` 파일(표준 원문, 저작권자 maengyo)을 M5를 기다리지 않고 지금 추가했다. `pyproject.toml`에는 이미 `license = "MIT"` (PEP 639 SPDX 표현식)이 있었고, LICENSE 파일 추가로 hatchling이 빌드 메타데이터에 `License-Expression: MIT` + `License-File: LICENSE`를 포함하게 됐다. `uv build`, `uv sync`, 전체 테스트 스위트(31개 통과, ruff 통과)로 검증했다.
- **의존성 라이선스 검토(license-compliance-expert).** 런타임 의존성 없음. dev 전용 의존성인 pytest(MIT), ruff(MIT)와 그 전이 의존성 colorama(BSD-3-Clause), iniconfig(MIT), packaging(Apache-2.0 OR BSD-2-Clause), pluggy(MIT), pygments(BSD-2-Clause) 모두 permissive 라이선스로 MIT 배포와 호환되며 copyleft 없음 — blocker 없음.
