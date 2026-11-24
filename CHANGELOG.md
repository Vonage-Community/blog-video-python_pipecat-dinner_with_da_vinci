# Changelog

All notable changes to this sample. After the tutorial release, only security fixes
and documentation corrections land here, as patch versions.

## [Unreleased] 1.0.0 (tutorial)

Not tagged yet: waiting for the live manual and persona tests with a designed voice.

- Started from a copy of `blog-video-python_pipecat-modular_voice_agent` (commit
  `1140c38`, MIT, © Vonage): browser app, FastAPI session API, limits, one process per
  agent, the Deepgram → OpenAI → ElevenLabs pipeline on Pipecat 1.16.0, transcript
  signals, and the waiting room.
- AI da Vinci: an AI portrayal of Leonardo da Vinci at Amboise in spring 1518, defined
  in `app/persona.py`, with a knowledge cutoff, an identity lock, and rules for quotes,
  disputed facts, and gossip.
- English with an Italian accent, or Italian, chosen per call. The language sets
  Deepgram, the reply language, ElevenLabs' language, and the fixed lines.
- A fixed, non-interruptible greeting that discloses he's an AI portrayal, and a fixed
  farewell after a long silence.
- A join screen with the disclosure, a banner for the whole call, the public-domain
  Melzi portrait with its credit, a glow while he speaks, and an honest status line.
- `GET /api/persona`, so the browser shows the same text the server enforces.
- An illustrated portrait (an imagined likeness made with ChatGPT), shown still, or as a
  talking portrait with Simli when `SIMLI_API_KEY` and `SIMLI_FACE_ID` are set.
- A dinner design: an invitation with a place card, a candlelit table, and one light
  disclosure line plus a tag on his frame. The greeting uses the guest's name.
- The browser can't add instructions or pick a voice that isn't in `.env`.
- `ELEVENLABS_VOICE_ID` is required and has no default: readers design their own voice.
- Audio is handed to the Vonage connector at playing speed, so Pipecat's "bot is
  speaking" matches what the guest hears. Before this, one word interrupted a reply
  after its first second, and the idle timer started mid-reply.
