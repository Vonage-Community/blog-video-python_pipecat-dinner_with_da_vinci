"""What the waiting room lets you choose for each call, and how the server checks it.

The browser sends its choices with POST /api/sessions. Nothing it sends is trusted:
every value is checked against an allowed list or range here, then copied onto the
agent's Settings. The defaults come from .env, so a call with no choices behaves
exactly like the server's configuration.

There is deliberately no free-text field: the browser can't add instructions on top of
the persona's rules (see app/persona.py).
"""

from __future__ import annotations

import unicodedata
from dataclasses import asdict, dataclass, replace
from typing import Any

from app import persona
from app.config import Settings

# The languages the persona is written for. Each one sets what Deepgram listens for,
# what the LLM answers in, and which greeting plays; the ElevenLabs voice stays the same.
LANGUAGES: dict[str, str] = {"en": "English", "it": "Italiano"}
assert set(LANGUAGES) == set(persona.LANGUAGES)

# How much silence ends your turn before Smart Turn decides you've finished.
REPLY_PAUSES: dict[str, float] = {"quick": 0.2, "relaxed": 0.5, "patient": 0.8}

MAX_KEYTERMS_PER_CALL = 20
SPEED_RANGE = (0.7, 1.2)  # what ElevenLabs accepts for streaming speech
INTERRUPT_WORDS_RANGE = (1, 5)


class CallOptionsError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class CallOptions:
    language: str
    guest_name: str
    keyterms: tuple[str, ...]
    openai_model: str
    voice_id: str
    voice_speed: float
    interrupt_min_words: int
    reply_pause: str

    @classmethod
    def defaults(cls, settings: Settings) -> CallOptions:
        return cls(
            language=settings.deepgram_language,
            guest_name="",
            keyterms=settings.deepgram_keyterms,
            openai_model=settings.openai_model,
            voice_id=settings.elevenlabs_voice_id,
            voice_speed=settings.elevenlabs_speed,
            interrupt_min_words=settings.interrupt_min_words,
            reply_pause="quick",
        )

    def to_json(self) -> dict[str, Any]:
        """The same camelCase names the browser sends."""
        fields = {**asdict(self), "keyterms": list(self.keyterms)}
        return {_JSON_NAMES[name]: value for name, value in fields.items()}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> CallOptions:
        """Rebuild options the server already checked (the agent process side)."""
        fields = {name: data[json_name] for name, json_name in _JSON_NAMES.items()}
        return cls(**{**fields, "keyterms": tuple(fields["keyterms"])})

    def apply_to(self, settings: Settings) -> Settings:
        """The agent's settings for this call."""
        return replace(
            settings,
            deepgram_language=self.language,
            guest_name=self.guest_name,
            deepgram_keyterms=self.keyterms,
            openai_model=self.openai_model,
            elevenlabs_voice_id=self.voice_id,
            elevenlabs_speed=self.voice_speed,
            interrupt_min_words=self.interrupt_min_words,
            vad_stop_secs=REPLY_PAUSES[self.reply_pause],
        )


_JSON_NAMES = {
    "language": "language",
    "guest_name": "guestName",
    "keyterms": "keyterms",
    "openai_model": "openaiModel",
    "voice_id": "voiceId",
    "voice_speed": "voiceSpeed",
    "interrupt_min_words": "interruptMinWords",
    "reply_pause": "replyPause",
}


def parse_call_options(raw: Any, settings: Settings) -> CallOptions:
    """Check the browser's choices. Raises CallOptionsError listing every problem."""
    defaults = CallOptions.defaults(settings)
    if raw is None:
        return defaults
    if not isinstance(raw, dict):
        raise CallOptionsError(["options must be an object"])
    problems: list[str] = []

    language = raw.get("language", defaults.language)
    if language not in LANGUAGES:
        problems.append(f"language must be one of {', '.join(LANGUAGES)}")

    keyterms_raw = raw.get("keyterms", list(defaults.keyterms))
    keyterms: tuple[str, ...] = ()
    if not isinstance(keyterms_raw, list) or not all(isinstance(t, str) for t in keyterms_raw):
        problems.append("keyterms must be a list of words")
    else:
        keyterms = tuple(dict.fromkeys(_clean(t)[:100] for t in keyterms_raw if _clean(t)))
        if len(keyterms) > MAX_KEYTERMS_PER_CALL:
            problems.append(f"Use at most {MAX_KEYTERMS_PER_CALL} keyterms")

    model = raw.get("openaiModel", defaults.openai_model)
    if model not in settings.openai_models:
        problems.append(f"openaiModel must be one of {', '.join(settings.openai_models)}")

    guest_name = raw.get("guestName", "")
    if not isinstance(guest_name, str):
        problems.append("guestName must be text")
        guest_name = ""
    guest_name = " ".join(_clean(guest_name).split())
    if guest_name and (
        len(guest_name) > persona.MAX_GUEST_NAME
        or len(guest_name.split()) > persona.MAX_GUEST_NAME_WORDS
        or not persona.GUEST_NAME.match(guest_name)
    ):
        problems.append(
            f"guestName must be a name: up to {persona.MAX_GUEST_NAME} characters and "
            f"{persona.MAX_GUEST_NAME_WORDS} words, letters, spaces, hyphens, and apostrophes"
        )

    if "instructions" in raw:
        problems.append("instructions can't be changed: the persona's rules are fixed")

    # Only the voices .env lists. A voice from the reader's account could be a clone.
    voice_id = raw.get("voiceId", defaults.voice_id)
    allowed_voices = {defaults.voice_id, *(v for v, _ in settings.elevenlabs_voices)}
    if voice_id not in allowed_voices:
        problems.append("voiceId must be one of the voices in ELEVENLABS_VOICES")

    speed = raw.get("voiceSpeed", defaults.voice_speed)
    if not _number_in(speed, *SPEED_RANGE):
        problems.append(f"voiceSpeed must be between {SPEED_RANGE[0]} and {SPEED_RANGE[1]}")

    min_words = raw.get("interruptMinWords", defaults.interrupt_min_words)
    if isinstance(min_words, bool) or not isinstance(min_words, int):
        problems.append("interruptMinWords must be a whole number")
    elif not INTERRUPT_WORDS_RANGE[0] <= min_words <= INTERRUPT_WORDS_RANGE[1]:
        problems.append(
            f"interruptMinWords must be between {INTERRUPT_WORDS_RANGE[0]} and "
            f"{INTERRUPT_WORDS_RANGE[1]}"
        )

    pause = raw.get("replyPause", defaults.reply_pause)
    if pause not in REPLY_PAUSES:
        problems.append(f"replyPause must be one of {', '.join(REPLY_PAUSES)}")

    if problems:
        raise CallOptionsError(problems)
    return CallOptions(
        language=language,
        guest_name=guest_name,
        keyterms=keyterms,
        openai_model=model,
        voice_id=voice_id,
        voice_speed=round(float(speed), 2),
        interrupt_min_words=min_words,
        reply_pause=pause,
    )


def _clean(text: str) -> str:
    """Drop control characters and trim."""
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C").strip()


def _number_in(value: Any, low: float, high: float) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and low <= value <= high
