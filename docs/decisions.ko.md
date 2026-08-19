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
