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

_LANGUAGES: tuple[Language, ...] = ("en", "ko")

# count >= 1: still-open-todos taunts, teasing but affectionate.
_TAUNT_LINES: dict[Language, list[str]] = {
    "en": [
        "Still {count} todos. They won't do themselves, you know.",
        "{count} todos are staring at you. Blink first?",
        "Look at that -- {count} things still waiting on you.",
        "{count} todos, zero excuses. I'm just saying.",
        "You've got {count} left. I'll be here. Watching.",
        "{count} todos and counting. No pressure. (Some pressure.)",
    ],
    "ko": [
        "아직 {count}개 남았는데? 할 일이 스스로 사라지진 않아.",
        "{count}개나 남았어? 나는 그냥 보고 있을게.",
        "이봐, {count}개가 아직도 널 기다리고 있어.",
        "{count}개 남았네. 핑계는 안 궁금해.",
        "{count}개... 오늘 안에 되긴 하는 거야?",
        "{count}개가 여기서 노숙 중이야. 집에 좀 보내주자?",
    ],
}

# count == 0: cheeky congratulations.
_CONGRATS_LINES: dict[Language, list[str]] = {
    "en": [
        "Empty list. Suspiciously productive today.",
        "Zero todos. Who even are you right now?",
        "All done. I'm almost proud of you.",
        "Nothing left. Don't let it go to your head.",
    ],
    "ko": [
        "다 했네? 오늘 좀 수상할 정도로 부지런한걸.",
        "할 일이 하나도 없어? 너 맞아?",
        "다 끝냈네. 조금 놀랐어.",
        "오늘은 봐줄게. 다 했으니까.",
    ],
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


def taunt(count: int, language: Language, rng: random.Random | None = None) -> str:
    """Pick a taunting line (count >= 1) or congrats line (count == 0).

    `rng` is injectable so callers can get deterministic output in tests.
    """
    chooser = rng if rng is not None else random.Random()
    pool = _TAUNT_LINES[language] if count >= 1 else _CONGRATS_LINES[language]
    line = chooser.choice(pool)
    return line.format(count=count)
