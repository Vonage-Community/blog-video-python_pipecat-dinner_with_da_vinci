"""The character's text: what must always be there, in both languages.

These check the words the code guarantees. How well the model follows the prompt
can only be checked in a live call; see docs/PERSONA_TEST.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import persona
from app.call_options import LANGUAGES

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def test_every_waiting_room_language_has_persona_text():
    assert set(LANGUAGES) == set(persona.LANGUAGES) == {"en", "it"}


@pytest.mark.parametrize(
    ("language", "ai_words"),
    [("en", "AI portrayal"), ("it", "intelligenza artificiale")],
)
def test_greeting_farewell_and_disclosure_say_it_is_an_ai(language, ai_words):
    text = persona.LANGUAGES[language]
    for line in (text.greeting, text.farewell, text.disclosure):
        assert ai_words in line
    assert "non è il vero" in text.banner if language == "it" else "not the real" in text.banner
    # The greeting discloses before it asks anything.
    assert text.greeting.index(ai_words) < text.greeting.index("?")


def test_the_prompt_sets_the_scene_cutoff_and_identity_lock():
    prompt = persona.SYSTEM_INSTRUCTION
    assert "spring evening in 1518" in prompt
    assert "nothing about anything after it" in prompt
    assert "say plainly that you are an AI portrayal" in prompt
    assert "Never present a sentence as something you wrote or said word for word" in prompt
    assert "historians still argue" in prompt
    assert "Never invent a story" in prompt


@pytest.mark.parametrize(("language", "rule"), [("en", "only English"), ("it", "only Italian")])
def test_the_language_rule_comes_last(language, rule):
    prompt = persona.system_instruction(language)
    assert prompt.startswith(persona.SYSTEM_INSTRUCTION)
    assert rule in prompt.splitlines()[-1]


def test_public_view_has_the_disclosure_and_an_existing_portrait():
    view = persona.public_view()
    assert view["name"] == "Leonardo da Vinci"
    assert set(view["languages"]) == {"en", "it"}  # type: ignore[arg-type]
    portrait = view["portrait"]
    assert (WEB_DIR / portrait["path"]).is_file()  # type: ignore[index]
    assert "Public domain" in portrait["credit"]  # type: ignore[index]


def test_never_called_leonardo_ai():
    # Leonardo.Ai is an AI product; the character is always "da Vinci" or the full name.
    everything = persona.SYSTEM_INSTRUCTION + persona.DISPLAY_NAME + str(persona.public_view())
    for text in persona.LANGUAGES.values():
        everything += text.greeting + text.farewell + text.disclosure + text.banner
    assert "Leonardo AI" not in everything
    assert "Leonardo.Ai" not in everything
