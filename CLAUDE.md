# CLAUDE.md

Maintainer notes for **blog-video-python_pipecat-dinner_with_da_vinci**, the sample for
the Vonage Developer Blog post *Dinner With da Vinci: Build an AI Persona With Vonage
Video*. This repository is the companion to a tutorial and must keep matching it.

## Scope

- One character: an AI portrayal of **Leonardo da Vinci**, at Clos Lucé (the manor of
  Cloux), Amboise, spring 1518, with no knowledge after that. English with an Italian
  accent, or Italian, per call.
- The modular pipeline from `blog-video-python_pipecat-modular_voice_agent`: Deepgram →
  OpenAI → ElevenLabs on Pipecat 1.16.0 with the Vonage Video Connector transport.
- Do **not** add: more characters, an avatar or lip-sync, a moving portrait, cloned or
  imitated voices, OpenAI Realtime, telephony, recordings, memory across calls, tools,
  or retrieval.
- This repo started as a copy of the modular agent repo (commit `1140c38`) and has no
  dependency on it. Never edit that repo from here.

## The persona's hard rules

- **Disclosure**, kept light: one line on the invitation, an *AI portrayal* tag on his
  frame for the whole call, and the fixed greeting, in both languages. The greeting is code (`fixed_speech`), never LLM output.
- **Identity lock:** sincerely asked, he always says he's an AI portrayal.
- **No invented quotes:** he never presents a saying as his words, even paraphrased.
- **Disputed facts** are acknowledged, not settled. Gossip is documented or labeled
  rumor, never invented.
- **Voice:** a Voice Design voice, never a clone, and never described as Leonardo's.
- **Portrait:** the public-domain Melzi drawing, static, with its credit shown.
- Never write "Leonardo AI" (Leonardo.Ai is a Canva product).
- The browser can't add instructions: `app/call_options.py` rejects them.
- Daniela reviews any change to the Italian text.

## Commands

```bash
uv sync                                      # local venv (Linux has the native connector)
uv run pytest -q                             # tests; Linux-only ones skip on macOS/Windows
uv run ruff check app tests && uv run ruff format --check app tests
uv run mypy
docker build --target test .                 # lint + types + tests inside Linux
docker compose up --build                    # run the app on http://localhost:8000
```

## Architecture rules

- `app/persona.py` holds everything about the character. `app/modular_agent.py` doesn't
  know who it plays.
- Keep the `Pipeline([...])` list readable: one line per stage.
- VAD belongs on `LLMUserAggregatorParams`, not on the transport params (Pipecat
  removed the transport field and ignores it silently).
- `pace_audio_to_real_time` must stay until the Vonage transport paces audio itself:
  without it, Pipecat thinks the bot stopped speaking about a second into each reply,
  so one word interrupts and the idle timer starts mid-reply.
- Fixed lines are one `TTSSpeakFrame` each (`fixed_speech`). Splitting them into one
  frame per sentence broke the Simli avatar: its service swallows `TTSStoppedFrame`, and
  back-to-back fixed frames left the turn bookkeeping cut short.
- `MicrophoneGate` drops audio until `POST /ready`; the greeting is sent once.
- The farewell uses the user aggregator's `user_idle_timeout`; the worker's idle
  timeout is 30 s longer as a backstop.
- Transcripts go agent process → pipe → server → Vonage Video signal (`send_signal`,
  type `transcript`) to the browser's connection only. The browser accepts only signals
  with no `from` connection. Signals use a separate Vonage client
  (vonage-python-sdk#323).
- Only the browser token is returned to the browser. API keys and the private key
  never leave the server. Logs go through `app.config.setup_logging`, which redacts them.

## Dependencies

- `pipecat-ai[deepgram,elevenlabs,openai,vonage-video-connector]==1.16.0` from PyPI;
  see `docs/DEPENDENCIES.md`. Never install the Vonage fork alongside it.
- `uv.lock` is committed; Docker uses `uv sync --frozen`.
- Check the real source of a new Pipecat version before using an API.

## Verification honesty

Mocked tests don't prove WebRTC audio, provider behavior, or how well the model follows
the persona. Any change touching media, the agent, the prompt, or dependencies needs
`docs/MANUAL_TEST.md` and `docs/PERSONA_TEST.md` with real credentials. Report anything
not run as NOT VERIFIED.

## Publishing

Don't create remotes, push, or tag without the maintainer's explicit approval.
