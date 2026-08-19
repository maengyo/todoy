# todoy — 요구사항

> English version: [requirements.md](requirements.md)

## 비전

메모 앱(Obsidian 등)이나 터미널에 적어둔 오늘의 할 일을 **까먹지 않도록**, 캐릭터가 화면에 나타나 말풍선으로 리마인드해주는 오픈소스 CLI 도구.

- GitHub에 공개되어 누구나 한 줄로 설치: `pipx install todoy` / `uv tool install todoy`.
- 개인 경로 하드코딩 금지 — 모든 설정은 `todoy init` 마법사와 `~/.config/todoy/config.toml`로.
- Obsidian은 **여러 소스 중 하나의 예시**일 뿐. 소스는 플러그인 구조이며, Obsidian 없이도 완전히 동작한다.

## 기능 요구사항

### 할 일 소스 (플러그인 구조)

- `sources/base.py` — `Source` 인터페이스: `get_todos() -> list[Todo]`. 새 소스(Notion, Todoist 등)는 파일 하나 추가로 만들 수 있어야 한다.
- `sources/markdown.py` — 지정한 폴더의 마크다운에서 할 일 추출 (Obsidian vault도 그냥 폴더).
  - `- 항목`, `- [ ] 항목` 줄을 할 일로 인식, `- [x]`는 완료로 제외.
  - "오늘의 할 일" = 오늘 수정된(mtime) 노트 + 사용자가 고정한 노트(예: `할 일.md`).
- `sources/builtin.py` — 자체 저장소. `todoy add "우유 사기"`, `todoy done 1`, `todoy list`로 터미널에서 바로 관리. 단순한 로컬 JSON 파일에 저장 (`~/.local/share/todoy/todos.json`, `TODOY_DATA_FILE`·`XDG_DATA_HOME` 지원).
- 여러 소스 동시 활성화 가능, config에서 선택.

### 표시 (2가지 모드)

- `todoy tui` — 터미널에 이모지/ASCII 캐릭터가 말풍선으로 오늘의 할 일을 출력. macOS/Linux/Windows 크로스 플랫폼. `.zshrc`에 넣어 새 터미널마다 뜨는 compact 모드(`todoy tui --brief`) 제공.
- `todoy overlay` — 데스크톱 위에 상주하는 투명 플로팅 캐릭터 창(macOS 우선, pyobjc). 설정된 주기(기본 30분)마다 말풍선으로 할 일을 띄우고, 클릭으로 스누즈/닫기/종료. display 레이어를 분리해 나중에 다른 OS 백엔드를 추가할 수 있는 구조.

### 캐릭터·상호작용 원칙 (2026-08-20 추가)

- **캐릭터 교체 가능.** 사용자가 캐릭터를 바꿀 수 있다: 자기 이미지(사진 등)를 넣거나 번들된 무저작권 기본 캐릭터 중 선택. config / `todoy init`으로 설정.
- **캐릭터는 지나다닐 뿐.** 리마인드하고 약올리기만 한다 — 할 일을 대신 완료해주지 않으며, 앱 안에서 영구히 안 보이게 하는 버튼도 없다. 끄려면 사용자가 직접 config를 수정해야 한다(의도적 마찰; 스누즈는 일시적으로만).
- **약오르는 말투.** 리마인드 메시지는 미완료 할 일을 두고 사용자를 장난스럽게 약올리고(메시지 팩, 영/한), 캐릭터 등장 연출도 같은 톤을 유지한다.
- **파일 지정.** 폴더 안 특정 파일을 할 일 소스로 지정 가능 — 마크다운 소스의 `pinned_notes` 설정으로 지원.
- **README 실동작 데모.** 실제 앱(TUI + 오버레이) 녹화를 GitHub README에 삽입 (M5).

### CLI

`todoy init`(대화형 설정) / `add` / `done` / `list` / `tui` / `overlay`. Python 3.11+, `pyproject.toml` 기반, 의존성 최소화.

## 품질 기준

- 새 사용자가 README만 보고 5분 안에 설치 → `todoy init` → 첫 리마인드까지 도달할 수 있어야 한다.
- TUI는 3개 OS에서 동작(CI에서 확인), 오버레이는 macOS에서 실동작 확인.
- 공개 저장소 품질: 타입 힌트, ruff 린트 통과, core 로직 테스트 커버리지.

## 마일스톤

| # | 범위 | 상태 |
|---|------|------|
| M1 | 프로젝트 뼈대(pyproject, git, 테스트) + `Todo` 모델 + builtin 소스 + `add`/`done`/`list` CLI | ✅ 완료 (2026-08-20) |
| M2 | 마크다운 소스 (Obsidian vault 호환) + `todoy init` 마법사 | ✅ 완료 (2026-08-20) |
| M3 | TUI 캐릭터 (크로스 플랫폼, `--brief` 모드) | ✅ 완료 (2026-08-20) |
| M4 | macOS 오버레이 캐릭터 (주기 알림, 스누즈) | ✅ 완료 (2026-08-20) |
| M5 | 릴리스 준비: README, MIT 라이선스, GitHub Actions CI, PyPI 배포, 데모 GIF | ✅ 완료 (2026-08-20, 첫 PyPI 태그 배포는 보류) |

각 마일스톤은 TDD로 진행하며, 교차 리뷰 통과 후에만 머지한다.
