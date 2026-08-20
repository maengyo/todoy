# 데모 자산 — 만드는 방법

> English version: [demo.md](demo.md)

README에는 실제로 실행 중인 앱에서 캡처한 두 자산이 커밋되어 있습니다:

- `demo/overlay-demo.gif` — macOS 오버레이(할 일 깃발을 든 질주하는 말).
  **앱의 실제 창을 자가 렌더링**해서 녹화: 작은 스크립트가 실제
  `_OverlayController`를 구동하고, 0.15초마다 캐릭터/메시지 창을
  `cacheDisplayInRect`로 스냅샷(화면 기록 권한 불필요)한 뒤 PNG 프레임을
  `ffmpeg -framerate 7 -i frame%03d.png -vf "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" -loop 0 out.gif`
  로 조립했습니다.
- `demo/tui.png` — 실제 `render_tui` 출력(기본 고양이 + `--ascii` 달팽이)을
  AppKit 텍스트 렌더러로 PNG에 그린 것.

## 다시 녹화 / 교체하려면

**오버레이 GIF (자가 렌더링, 아무 개발 Mac, 권한 불필요):** 프레임 레코더를
변형하세요 — `OverlayOptions`(캐릭터/이동/메시지 스타일 선택)로 컨트롤러를
구동하고, 반복 `NSTimer`로 `char_window`/`bubble_window`의 content view를
PNG로 스냅샷한 뒤 위의 ffmpeg 팔레트 명령으로 조립. 실제 할 일이 노출되지
않도록 임시 `TODOY_DATA_FILE`을 쓰세요.

**오버레이 실화면 녹화 (선택, 더 예쁨):** 임시 환경변수 설정 후
**Cmd-Shift-5**로 화면 하단 영역을 녹화하며
`uv sync --extra overlay && uv run todoy overlay --interval 1` 실행, 변환은
`ffmpeg -i in.mov -vf "fps=12,scale=760:-1" demo/overlay-demo.gif`.

**터미널 워크스루 GIF (선택):** `demo/demo.tape`는 바로 쓸 수 있는
[VHS](https://github.com/charmbracelet/vhs) 스크립트입니다
(`brew install vhs` 후 `vhs demo/demo.tape`) — 임시 `demo/demo-tmp/` 저장소로
add/list/tui/done을 재생해 `demo/todoy.gif`를 만듭니다. 녹화했다면 README의
`demo/tui.png` 옆에(또는 대신) 넣으세요.

## 파일 위치

```
demo/
├── demo.tape          # VHS 스크립트 (텍스트, 커밋됨)
├── overlay-demo.gif   # 라이브 오버레이 녹화 (커밋됨)
└── tui.png            # 실제 TUI 출력 (커밋됨)
```

GIF는 적당한 크기로(README 렌더 폭 ~880px, 2MB 이하 권장), 실제 데이터
파일로는 절대 녹화하지 마세요.
