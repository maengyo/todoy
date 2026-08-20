# todoy

> English version: [README.md](README.md)

오늘의 할 일을 까먹지 않게 해주는 캐릭터 — 터미널에서도, 데스크톱에서도.

**상태: 개발 중.** M1(코어 CLI), M2(마크다운/Obsidian 소스 + `todoy init`),
M3(`todoy tui`), M4(`todoy overlay`, macOS), M5(릴리스 준비: CI, PyPI 배포, 문서)까지
완료됐습니다 — [로드맵](docs/requirements.ko.md#마일스톤) 참고. 아직 PyPI에 배포된
버전은 없으니, 지금은 아래처럼 소스에서 설치하세요.

## 데모

실제로 실행 중인 데스크톱 오버레이 — 말이 화면 하단을 질주하며 오늘의 할 일이
적힌 깃발을 들고 다닙니다 (라이브 앱의 실제 창을 자가 렌더링해 캡처):

![todoy 오버레이: 깃발 든 질주하는 말](demo/overlay-demo.gif)

TUI 실제 출력 (기본 고양이, 그리고 `--ascii` 모드의 달팽이):

![todoy tui](demo/tui.png)

녹화 방법은 [docs/demo.ko.md](docs/demo.ko.md) 참고.

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

관리 명령: `todoy rm <id>` 삭제, `todoy pin <id>` / `unpin <id>` 고정(고정된
할 일은 📌 표시가 붙고 일일 청소에서 살아남음), `todoy add --pin`은 생성과 동시에
고정. config `[general]`에 `daily_clear = true`를 켜면 매일 첫 사용 시 어제까지의
고정 안 된 할 일이 자동으로 비워집니다 — 리스트는 매일 새로, 고정 태스크만 유지.

### 시간 알람

할 일에 시간을 붙이면 오버레이가 그 시각에 그 메시지만 정확히 띄웁니다:

```console
$ todoy add "스탠드업 회의" --at 9:55
Added #3: 스탠드업 회의

$ todoy list
  3. 09:55 스탠드업 회의
```

마크다운 노트도 됩니다: `- [ ] 14:00 회의`는 14:00에 울립니다. 알람은 할 일당
하루 한 번(스누즈 시 재예약), 주기 리마인드와는 독립적으로 동작합니다.

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
- 캐릭터 15종: cat(기본), dog, ghost, robot, horse, turtle, snail, penguin,
  frog, bee, owl, unicorn, dino, alien, crab — `--character 이름`,
  `--lang en|ko`, 이모지 없는 터미널엔 `--ascii`.
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
- 움직임과 메시지 표시 방식 고르기:
  `todoy overlay --movement gallop --message-style flag --character horse`
  — 말이 할 일이 적힌 깃발을 들고 화면을 질주합니다.
  이동: `walk`(기본) / `hop` / `float` / `dash` / `gallop` / `still`.
  메시지 스타일: `bubble`(기본, 제자리) / `flag`(캐릭터와 함께 달림).
  등장 효과: `--bubble-effect pop`(기본) / `fade` / `slide` / `shake` / `none`.
  config `[display]`의 `movement` / `message_style` / `bubble_effect`로 영구 설정.
- `todoy overlay --once`는 GUI 없이 리마인드 텍스트만 출력합니다
  (모든 OS에서 동작 — 스크립트·미리보기용).
- 다른 플랫폼: display 레이어는 플러그인 구조입니다. Linux/Windows 오버레이
  백엔드 기여를 환영합니다.

오버레이 실행 중에는 **메뉴바 아이콘**(캐릭터 이모지)이 생깁니다. 클릭하면 퀵
패널이 열려 할 일(+선택적 `HH:MM` 알람 시간)을 입력하고 리턴만 치면 등록 끝.
같은 패널에서 오늘의 리스트를 체크(✓)·삭제(✕)·고정(📌)할 수 있습니다 — 단,
노트에서 온 할 일은 읽기 전용입니다(todoy는 노트를 절대 수정하지 않음).
리마인드 말풍선 자체는 여전히 스누즈/종료뿐 — 리스트 관리는 일부러 당신 몫입니다.

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
