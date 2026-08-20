# todoy

> English version: [README.md](README.md)

오늘의 할 일을 까먹지 않게 해주는 캐릭터 — 터미널에서도, 데스크톱에서도.

**상태: 개발 중.** M1(코어 CLI), M2(마크다운/Obsidian 소스 + `todoy init`),
M3(`todoy tui`), M4(`todoy overlay`, macOS), M5(릴리스 준비: CI, PyPI 배포, 문서)까지
완료됐습니다 — [로드맵](docs/requirements.ko.md#마일스톤) 참고. 아직 PyPI에 배포된
버전은 없으니, 지금은 아래처럼 소스에서 설치하세요.

## 데모

<!-- ![todoy 데모](demo/todoy.gif) — 녹화되면 주석 해제 -->
<!-- ![todoy 오버레이 데모](demo/overlay.gif) — 녹화되면 주석 해제 -->

CLI/TUI와 macOS 오버레이 녹화는 아직 준비되지 않았습니다 — 어떻게 녹화할지
(`vhs demo/demo.tape`, macOS 화면 녹화)와 어디에 저장될지(`demo/todoy.gif`,
`demo/overlay.gif`)는 [docs/demo.ko.md](docs/demo.ko.md)를 참고하세요. 이
README에 나오는 명령어들은 지금도 모두 그대로 동작합니다.

## 설치 (지금은 소스에서)

Python 3.11+ 필요.

```console
$ git clone https://github.com/maengyo/todoy.git
$ cd todoy
$ uv sync            # 또는: pip install -e .
$ uv run todoy list  # 또는 venv 안에서: todoy list
```

PyPI 배포 자동화는 준비됐지만(`pipx install todoy` / `uv tool install todoy` —
[`.github/workflows/release.yml`](.github/workflows/release.yml) 참고), 아직
배포된 버전이 없습니다. 첫 태그 릴리스가 나올 때까지는 소스에서 설치하세요.

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
- 움직임과 말풍선 등장 방식 고르기:
  `todoy overlay --movement hop --bubble-effect shake` — 이동은
  `walk`(기본) / `hop` / `float` / `dash` / `still`, 말풍선 효과는
  `pop`(기본) / `fade` / `slide` / `shake` / `none`. config `[display]`의
  `movement` / `bubble_effect`로 영구 설정.
- `todoy overlay --once`는 GUI 없이 리마인드 텍스트만 출력합니다
  (모든 OS에서 동작 — 스크립트·미리보기용).
- 다른 플랫폼: display 레이어는 플러그인 구조입니다. Linux/Windows 오버레이
  백엔드 기여를 환영합니다.

## 로드맵

M1~M5가 모두 구현됐습니다. 남은 건 코드가 아니라 운영 작업입니다: 첫 릴리스에
태그를 달고 푸시하면 CI가 실제로 PyPI에 배포합니다.

자세히: [docs/requirements.ko.md](docs/requirements.ko.md) ·
결정/변경 기록: [docs/decisions.ko.md](docs/decisions.ko.md)

## 개발

```console
$ uv sync
$ uv run pytest
$ uv run ruff check .
$ uv run ruff format --check .
```

CI(`.github/workflows/ci.yml`)가 매 push/pull request마다 Linux/macOS/Windows,
Python 3.11·3.13 조합으로 동일한 검사를 돌립니다.

기여를 환영합니다 — 소스 플러그인 인터페이스(`src/todoy/sources/`, `base.py`의
`Source`)는 M2에서 안정화됐습니다.

## 라이선스

MIT — [LICENSE](LICENSE) 참고.
