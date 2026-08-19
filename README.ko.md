# todoy

> English version: [README.md](README.md)

오늘의 할 일을 까먹지 않게 해주는 캐릭터 — 터미널에서도, 데스크톱에서도.

**상태: 개발 중.** M1(코어 CLI), M2(마크다운/Obsidian 소스 + `todoy init`),
M3(`todoy tui`), M4(`todoy overlay`, macOS)가 완료됐습니다 — 남은 건 릴리스 준비(M5)입니다
([로드맵](docs/requirements.ko.md#마일스톤)).

## 지금 되는 것

로컬 JSON 파일 기반의 표준 라이브러리 전용 할 일 CLI + 노트에서 가져오는 할 일:

```console
$ todoy add "우유 사기"
Added #1: 우유 사기

$ todoy list
  1. 우유 사기

$ todoy done 1
Done #1: 우유 사기

$ todoy list --all
  1. [x] 우유 사기
```

할 일은 `~/.local/share/todoy/todos.json`에 저장됩니다 (`XDG_DATA_HOME` 지원,
`TODOY_DATA_FILE` 환경변수로 파일 경로 전체 교체 가능).

### 노트에서 할 일 가져오기 (Obsidian 호환)

`todoy init`을 실행해 마크다운 폴더를 지정하세요 — Obsidian vault를 그대로 쓰면 됩니다.
오늘 수정된 노트와 고정(pinned)한 노트의 `- [ ] 할 일` / `- 할 일` 줄이
`todoy list`에 합쳐져 나옵니다 (`- [x]` 완료 줄은 제외):

```console
$ todoy init
Enable markdown source? [y/N] y
Notes folder path: ~/notes
Pinned notes (comma-separated, optional): 할 일.md
Reminder interval in minutes [30]:
Config written to ~/.config/todoy/config.toml

$ todoy list
  1. 우유 사기
  - 회의 준비
  - 은행 전화
```

## 설치 (지금은 소스에서)

Python 3.11+ 필요.

```console
$ git clone https://github.com/maengyo/todoy.git
$ cd todoy
$ uv sync            # 또는: pip install -e .
$ uv run todoy list  # 또는 venv 안에서: todoy list
```

PyPI 배포(`pipx install todoy` / `uv tool install todoy`)는 M5에서 제공됩니다.

### 캐릭터 만나기 (`todoy tui`)

캐릭터가 말풍선으로 오늘의 할 일을 전해줍니다 — 살짝 약올리는 맛과 함께:

```console
$ todoy tui
.---------------------------------------------.
| 3개가 여기서 노숙 중이야. 집에 좀 보내주자? |
| [#1] 우유 사기                              |
| * 회의 준비                                 |
| * 은행 전화                                 |
`---------------------------------------------'
  /
🐱
```

- `todoy tui --brief`는 한 줄만 출력합니다 — `.zshrc` / `.bashrc`에 넣으면
  새 터미널마다 잔소리를 들을 수 있어요: `🐱 3 todos: 우유 사기 (+2 more)`
- `--character cat|dog|ghost|robot`, `--lang en|ko`, 이모지 없는 터미널엔 `--ascii`.
- 메시지는 할 일을 놀리지, 당신을 공격하지 않습니다. 캐릭터는 알려줄 뿐 — 끝내는 건 여전히 당신 몫.

### 데스크톱 위의 캐릭터 (`todoy overlay`, macOS)

```console
$ uv sync --extra overlay   # 또는: pip install -e '.[overlay]'
$ todoy overlay
```

투명한 캐릭터가 화면 하단을 배회하다가, 설정한 주기(기본 30분,
`[general] reminder_interval_minutes`)마다 오늘의 할 일을 말풍선으로 띄웁니다.
말풍선 버튼은 **스누즈**(일시)와 **종료** 둘뿐 — 일부러 그렇게 만들었습니다:
캐릭터는 할 일을 대신 완료해주지 않고, 영구 음소거 버튼도 없습니다. 완전히
끄려면 직접 config를 고쳐야 합니다. 이 귀찮음이 기능입니다.

- 캐릭터를 내 이미지로 교체: `~/.config/todoy/config.toml`의 `character_image`
  설정(또는 `todoy init` 질문에 답하기).
- `todoy overlay --once`는 GUI 없이 리마인드 텍스트만 출력합니다
  (모든 OS에서 동작 — 스크립트·미리보기용).
- 다른 플랫폼: display 레이어는 플러그인 구조입니다. Linux/Windows 오버레이
  백엔드 기여를 환영합니다.

## 로드맵


- **M5** — 릴리스: CI, PyPI 배포(`pipx install todoy`), 데모 녹화

자세히: [docs/requirements.ko.md](docs/requirements.ko.md) ·
결정/변경 기록: [docs/decisions.ko.md](docs/decisions.ko.md)

## 개발

```console
$ uv sync
$ uv run pytest
$ uv run ruff check .
```

플러그인 인터페이스가 안정화되면(M2 이후) 기여를 환영합니다.

## 라이선스

MIT — [LICENSE](LICENSE) 참고.
