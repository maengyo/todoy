"""Taunting message pack: language resolution and taunt/congrats line selection.

Tone is teasing but affectionate, never insulting (docs/requirements.md
"Character & interaction principles") -- the character reminds, it never
completes todos for you.
"""

from __future__ import annotations

import os
import random
from typing import Literal

Language = Literal["en", "ko"]
MessageKind = Literal["taunt", "congrats"]

_LANGUAGES: tuple[Language, ...] = ("en", "ko")

_VoicePack = dict[Language, dict[MessageKind, list[str]]]

_VOICES: dict[str, _VoicePack] = {
    "default": {
        "en": {
            "taunt": [
                "On deck: {count}. The list is loitering.",
                "Todo count: {count}. The pile looks comfy.",
                "Waiting count: {count}. Tasks brought snacks.",
                "Still queued: {count}. Tasks love drama.",
            ],
            "congrats": [
                "Empty list. The tasks finally ran out.",
                "All clear. The list looks startled.",
                "Zero left. Suspiciously tidy.",
            ],
        },
        "ko": {
            "taunt": [
                "할 일 {count}개, 아직 자리 펴고 있어.",
                "목록에 {count}개가 눌러앉았네.",
                "할 일 {count}개가 눈치 보는 척해.",
                "{count}개 남음. 목록이 버티는 중.",
            ],
            "congrats": [
                "목록 비었네. 할 일들이 항복했어.",
                "끝! 목록이 어색하게 조용해.",
                "남은 일 0개. 오늘은 깔끔해.",
            ],
        },
    },
    "knightly": {
        "en": {
            "taunt": [
                "Quest count: {count}. Tasks await trial.",
                "Errand count: {count}. They guard the gate.",
                "Duty count: {count}. They hold the bridge.",
                "Task count: {count}. Refusing retreat.",
            ],
            "congrats": [
                "Quest board clear. Honor restored.",
                "No quests remain. The realm exhales.",
                "All duties vanquished. Trumpets later.",
            ],
        },
        "ko": {
            "taunt": [
                "퀘스트 {count}개, 성문 앞 대기 중.",
                "임무 {count}개가 방패 뒤에 숨어.",
                "할 일 {count}개, 기사단 점호 중.",
                "{count}개 남음. 목록의 용기가 가상해.",
            ],
            "congrats": [
                "퀘스트 완료. 왕국이 조용해.",
                "임무 전멸. 나팔은 마음속으로.",
                "목록 클리어. 명예롭게 끝.",
            ],
        },
    },
    "robotic": {
        "en": {
            "taunt": [
                "BEEP: queue={count}. Tasks still pending.",
                "Status code {count}: tasks remain cheeky.",
                "Todo scan: {count}. Resistance detected.",
                "Open count: {count}. List refuses idle.",
            ],
            "congrats": [
                "BEEP: queue empty. Verified.",
                "Zero pending. Robot applause: whirr.",
                "All tasks cleared. Beep boop victory.",
            ],
        },
        "ko": {
            "taunt": [
                "삐빅, 대기열 {count}개 감지.",
                "상태: {count}개 보류. 목록이 깜빡.",
                "할 일 {count}개, 처리 신호 대기.",
                "부웅. {count}개가 아직 반짝여.",
            ],
            "congrats": [
                "대기열 0. 삐빅, 정리 완료.",
                "보류 없음. 회로가 평온해.",
                "전부 완료. 로봇 박수 위잉.",
            ],
        },
    },
    "spooky": {
        "en": {
            "taunt": [
                "Wooo count: {count}. Tasks haunt the list.",
                "Ghost count: {count}. Todos rattle chains.",
                "Spooky scan: {count}. The list whispers.",
                "Boo. Open count: {count}. Mist drifts.",
            ],
            "congrats": [
                "No haunts remain. Woooo, peaceful.",
                "Empty list. The shadows look bored.",
                "All clear. Even the cobwebs clapped.",
            ],
        },
        "ko": {
            "taunt": [
                "우우, 할 일 {count}개가 둥둥.",
                "목록 귀신 {count}개, 아직 안 감.",
                "스산하게 {count}개 남았어.",
                "할 일 {count}개, 커튼 뒤에서 빼꼼.",
            ],
            "congrats": [
                "유령 퇴근. 목록이 고요해.",
                "0개 남음. 으스스하게 깔끔해.",
                "전부 성불. 목록도 한숨 푹.",
            ],
        },
    },
    "bouncy": {
        "en": {
            "taunt": [
                "Bounce count: {count}. Todos wobble around.",
                "Boing! Open count: {count}. Jelly jiggles.",
                "Todo blob count {count}. Still squishing.",
                "Hop check: {count}. The list keeps bouncing.",
            ],
            "congrats": [
                "All clear. Big bounce, tiny list.",
                "Zero left. The list went splat-happy.",
                "Done pile: empty. Boing approved.",
            ],
        },
        "ko": {
            "taunt": [
                "통통, 할 일 {count}개가 튀어.",
                "개굴개굴 {count}개, 목록 위 점프.",
                "말랑한 {count}개가 아직 꿈틀.",
                "할 일 {count}개, 젤리처럼 버텨.",
            ],
            "congrats": [
                "다 끝! 말랑하게 박수.",
                "0개 남음. 목록이 통 하고 비었어.",
                "전부 클리어. 개운하게 폴짝.",
            ],
        },
    },
    "salty": {
        "en": {
            "taunt": [
                "Ahoy count: {count}. Tasks cling to deck.",
                "Open tide: {count}. Todos splash about.",
                "Still aboard: {count}. The list smells briny.",
                "Deck check: {count}. Tasks refuse shore leave.",
            ],
            "congrats": [
                "All clear. Calm seas for the list.",
                "Zero aboard. The deck is gleaming.",
                "Nothing left. Tiny victory splash.",
            ],
        },
        "ko": {
            "taunt": [
                "출항 대기 {count}개, 갑판에 찰싹.",
                "할 일 {count}개가 물살 타고 버텨.",
                "짠내 나는 {count}개, 아직 선상.",
                "목록에 {count}개, 파도처럼 출렁.",
            ],
            "congrats": [
                "갑판 깨끗. 할 일들이 하선했어.",
                "0개 남음. 잔잔한 목록이야.",
                "전부 완료. 작은 물보라 축하.",
            ],
        },
    },
    "breezy": {
        "en": {
            "taunt": [
                "Wind count: {count}. Tasks flutter nearby.",
                "Updraft count: {count}. Breeze loops.",
                "Open skies: {count}. The list keeps flapping.",
                "Still aloft: {count}. Tasks ride the breeze.",
            ],
            "congrats": [
                "All clear. The list caught a tailwind.",
                "Zero left. Smooth air ahead.",
                "Done and dusted. Tiny wing salute.",
            ],
        },
        "ko": {
            "taunt": [
                "바람 타고 {count}개가 팔랑.",
                "할 일 {count}개, 아직 공중 선회.",
                "목록 위 {count}개가 날갯짓 중.",
                "산들산들 {count}개, 내려올 생각 없음.",
            ],
            "congrats": [
                "맑은 하늘. 목록도 가벼워.",
                "0개 남음. 바람이 시원해.",
                "전부 착륙. 목록이 조용해.",
            ],
        },
    },
    "feline": {
        "en": {
            "taunt": [
                "Purr count: {count}. Tasks bat at the list.",
                "Meow. Open count: {count}. Tail twitches.",
                "Todo count: {count}. The list naps on them.",
                "{count} in the bowl. The tasks pretend calm.",
            ],
            "congrats": [
                "All clear. Purr protocol engaged.",
                "Zero left. The list gets a slow blink.",
                "Done. Tiny paw stamp of approval.",
            ],
        },
        "ko": {
            "taunt": [
                "냥, 할 일 {count}개가 발끝에 톡.",
                "목록에 {count}개, 꼬리만 살랑.",
                "그르릉. {count}개가 아직 식빵 중.",
                "할 일 {count}개, 냥냥 버티네.",
            ],
            "congrats": [
                "다 했냥. 목록이 골골거려.",
                "0개 남음. 천천히 눈 깜빡.",
                "할 일 없음. 발도장 쾅.",
            ],
        },
    },
    "gamer": {
        "en": {
            "taunt": [
                "Level queue: {count}. Tasks need clearing.",
                "Quest log count {count}. Enemies: chores.",
                "XP waiting: {count}. Todos are blinking.",
                "Side quests open: {count}. Pixels judge them.",
            ],
            "congrats": [
                "Quest log clear. High score vibe.",
                "Zero left. GG, list defeated.",
                "All clear. Bonus stage unlocked.",
            ],
        },
        "ko": {
            "taunt": [
                "퀘스트 로그 {count}개, 깜빡깜빡.",
                "할 일 {count}개, 아직 스폰 중.",
                "픽셀 경고: {count}개가 버팀.",
                "사이드퀘 {count}개, 보상 대기.",
            ],
            "congrats": [
                "로그 클리어. GG.",
                "0개 남음. 보너스 스테이지!",
                "전부 클리어. 픽셀 폭죽.",
            ],
        },
    },
}


def resolve_language(lang: str | None = None) -> Language:
    """Resolve which language to use, in order of precedence.

    1. Explicit `lang` argument, if it is "en" or "ko".
    2. $TODOY_LANG, if set to "en" or "ko".
    3. "ko", if $LANG or $LC_ALL starts with "ko".
    4. "en" otherwise.
    """
    if lang in _LANGUAGES:
        return lang  # type: ignore[return-value]

    env_lang = os.environ.get("TODOY_LANG")
    if env_lang in _LANGUAGES:
        return env_lang  # type: ignore[return-value]

    for env_var in ("LANG", "LC_ALL"):
        value = os.environ.get(env_var)
        if value and value.lower().startswith("ko"):
            return "ko"

    return "en"


def taunt(
    count: int,
    language: Language,
    rng: random.Random | None = None,
    *,
    voice: str = "default",
) -> str:
    """Pick a taunting line (count >= 1) or congrats line (count == 0).

    `rng` is injectable so callers can get deterministic output in tests.
    """
    chooser = rng if rng is not None else random.Random()
    message_key: MessageKind = "taunt" if count >= 1 else "congrats"
    pool = _message_pool(voice, language, message_key)
    line = chooser.choice(pool)
    return line.format(count=count)


def _message_pool(voice: str, language: str, message_key: MessageKind) -> list[str]:
    default_pack = _VOICES["default"]
    fallback_language = language if language in default_pack else "en"
    fallback_pool = default_pack[fallback_language][message_key]

    voice_pack = _VOICES.get(voice)
    if voice_pack is None:
        return fallback_pool

    language_pack = voice_pack.get(language)  # type: ignore[arg-type]
    if language_pack is None:
        return fallback_pool

    return language_pack.get(message_key, fallback_pool)
