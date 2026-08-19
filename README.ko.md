# todoy

> English version: [README.md](README.md)

오늘의 할 일을 까먹지 않게 해주는 캐릭터 — 터미널에서도, 데스크톱에서도.

**상태: 개발 중.** M1(코어 모델 + builtin 저장소 + CLI)이 완료됐습니다. 마크다운/Obsidian
소스, TUI 캐릭터, macOS 오버레이는 [로드맵](docs/requirements.ko.md#마일스톤)에 있습니다.

## 지금 되는 것

로컬 JSON 파일 기반의 표준 라이브러리 전용 할 일 CLI:

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

## 설치 (지금은 소스에서)

Python 3.11+ 필요.

```console
$ git clone https://github.com/maengyo/todoy.git
$ cd todoy
$ uv sync            # 또는: pip install -e .
$ uv run todoy list  # 또는 venv 안에서: todoy list
```

PyPI 배포(`pipx install todoy` / `uv tool install todoy`)는 M5에서 제공됩니다.

## 로드맵

- **M2** — 마크다운 소스(노트 폴더 아무거나 지정 — Obsidian vault 포함) + 대화형 `todoy init` 마법사
- **M3** — `todoy tui`: 캐릭터가 말풍선으로 오늘의 할 일을 보여줌; 셸 rc용 `--brief` 모드
- **M4** — `todoy overlay`: 데스크톱 플로팅 캐릭터(macOS 우선), 주기 알림과 스누즈
- **M5** — 릴리스: 전체 문서, MIT 라이선스, CI, PyPI

자세히: [docs/requirements.ko.md](docs/requirements.ko.md) ·
결정/변경 기록: [docs/decisions.ko.md](docs/decisions.ko.md)

## 개발

```console
$ uv sync
$ uv run pytest
$ uv run ruff check .
```

플러그인 인터페이스가 안정화되면(M2 이후) 기여를 환영합니다. 라이선스: MIT (파일은 M5에서 추가).
