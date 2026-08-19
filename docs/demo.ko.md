# 데모 자산 녹화하기

> English version: [demo.md](demo.md)

README에는 아직 녹화되지 않은 GIF 두 개가 들어갑니다:

- `demo/todoy.gif` — CLI/TUI 흐름 (`todoy add`, `todoy list`, `todoy tui`,
  `todoy done`).
- `demo/overlay.gif` — macOS 데스크톱 오버레이 (`todoy overlay`).

녹화 도구(`vhs`, `asciinema`/`agg`)도 macOS 화면 녹화도 모든 개발 머신에
설치돼 있진 않으므로, 이 GIF들은 사람이 직접 녹화해서 바이너리로 커밋합니다.
이 문서는 다음에 녹화할 사람을 위한 안내입니다.

## `demo/todoy.gif` — CLI/TUI, VHS 사용

1. [VHS](https://github.com/charmbracelet/vhs) 설치:

   ```console
   $ brew install vhs
   ```

2. 저장소 루트에서 tape 스크립트를 실행합니다:

   ```console
   $ vhs demo/demo.tape
   ```

   `todoy add`(×2), `todoy list`, `todoy tui`, `todoy tui --brief`,
   `todoy done 1`, `todoy tui`를 순서대로 재생합니다. `uv run todoy`로
   실행하며, 실제 할 일 대신 임시 `demo/demo-tmp/` 데이터/설정 파일을 쓰고,
   녹화하는 머신의 로케일과 무관하게 항상 같은 결과가 나오도록
   `TODOY_LANG=en`을 고정합니다. 결과물은 `demo/todoy.gif`에 저장됩니다.

3. GIF를 확인(용량, GitHub README 폭 기준 가독성 — 800~900px 정도가 적당)한
   뒤 커밋합니다.

타이밍을 조정하거나 명령을 추가하려면 `demo/demo.tape`를 직접 편집하세요 —
`Type`/`Sleep`/`Env`/`Hide`/`Show`는
[VHS 명령 레퍼런스](https://github.com/charmbracelet/vhs#vhs-command-reference)를
참고하세요.

## `demo/overlay.gif` — macOS 오버레이, 화면 녹화 사용

오버레이는 실제 `NSWindow`(`src/todoy/display/overlay/macos.py` 참고)라서
VHS 같은 터미널 녹화 도구로는 잡히지 않습니다 — 실제 화면 녹화가 필요합니다.

1. 실제 할 일이 녹화에 나오지 않도록 임시 설정을 준비합니다:

   ```console
   $ export TODOY_DATA_FILE=/tmp/todoy-overlay-demo/todos.json
   $ export TODOY_CONFIG_FILE=/tmp/todoy-overlay-demo/config.toml
   $ mkdir -p /tmp/todoy-overlay-demo
   $ uv run todoy add "buy milk"
   $ uv run todoy add "prepare the meeting"
   ```

2. **Cmd-Shift-5**로 화면 녹화를 시작하고, 캐릭터가 나타날 영역(화면 하단)
   근처의 작은 범위를 선택한 뒤 녹화를 시작합니다.

3. 리마인더 말풍선이 빨리 뜨도록 짧은 간격으로 오버레이를 실행하고,
   전체 흐름(캐릭터 이동, 말풍선, 스누즈/종료)을 끝까지 지켜봅니다:

   ```console
   $ uv sync --extra overlay
   $ uv run todoy overlay --interval 1
   ```

4. 녹화를 멈춥니다(Cmd-Shift-5 정지 버튼 또는 메뉴바 아이콘). `.mov` 파일이
   저장되며, GIF로 변환한 뒤(예: `ffmpeg -i in.mov -vf
   "fps=12,scale=600:-1" demo/overlay.gif`) `demo/overlay.gif`로 커밋합니다.

## 파일 위치

```
demo/
├── demo.tape     # VHS 스크립트 (커밋됨, 텍스트)
├── todoy.gif     # CLI/TUI 녹화 (커밋 예정, 바이너리 — 아직 추가 안 됨)
└── overlay.gif   # macOS 오버레이 녹화 (커밋 예정, 바이너리 — 아직 추가 안 됨)
```

두 GIF가 녹화·커밋되기 전까지는 README의 데모 섹션 링크가 404가 뜹니다 —
해당 섹션의 안내 문구를 참고하세요.
