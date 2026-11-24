# Dinner With da Vinci: an AI persona voice agent on Vonage Video (Pipecat)

Join a Vonage Video call and have dinner with an AI portrayal of Leonardo da Vinci, set
on a spring evening in 1518 at his house in Amboise. He speaks English with an Italian
accent, or Italian, and you're the guest from the future. Deepgram transcribes what you
say, OpenAI writes his reply in character, and ElevenLabs speaks it in a voice you
design, all connected by a [Pipecat](https://docs.pipecat.ai) pipeline.

> **This is an AI portrayal, not Leonardo da Vinci.** The page says so before you join
> and for the whole call, and he says so in his first sentence. His answers can be
> wrong, nobody knows how Leonardo sounded, and he can't vouch for any quotation.

> **Docker required.** The native Vonage Video Connector SDK runs on Linux, so the
> agent runs in a Linux container. macOS and Windows users can use Docker Desktop;
> your browser connects to it on `localhost`.

## What you will build

- A **join screen** with the AI-portrayal notice, his portrait, and a choice of
  language: *English, with an Italian accent* or *Italiano*.
- A **persona** in one file, [`app/persona.py`](app/persona.py): the scene, a knowledge
  cutoff of spring 1518, his personality, and rules for quotes, disputed facts, gossip,
  and the question "are you real?"
- A **fixed greeting** that discloses he's an AI portrayal. It's text in the code, not
  something the model writes, so every call opens with it.
- A **call page** with his still portrait, which glows while he speaks (nothing about
  his face moves), a banner that stays on screen, and an honest status line: greeting,
  speaking, thinking, or your turn.
- A **transcript panel**: what Deepgram heard, what he said, and how long each stage
  took. It reaches the page as Vonage Video signals, and nothing is stored.
- A **farewell**: if you go quiet for two minutes, he says goodnight and the call ends.
- Behind the scenes: the same FastAPI server, routed Vonage Video session, separate
  browser and agent tokens, limits, and one process per agent as a plain modular voice
  agent.

## How it works

```text
Browser (Vonage Video Web SDK) ⇄ Vonage Video routed session ⇄ Pipecat agent (Docker)
  transport.input → MicrophoneGate → Deepgram → user turn (Silero VAD + Smart Turn v3)
  → OpenAI (persona prompt) → ElevenLabs (your designed voice) → transport.output
```

| Layer | Where | What it does |
|---|---|---|
| Persona | `app/persona.py` | Scene, personality, and the lines he would and wouldn't say |
| Knowledge cutoff | `app/persona.py` | Nothing after spring 1518. Told about the modern world, he asks how it works. |
| Memory | `app/modular_agent.py` | The LLM context keeps the whole dinner. Nothing is saved after the call. |
| Voice | ElevenLabs Voice Design, `.env` | A designed voice, not a clone, speaking both languages |
| Honest status | `web/` | The notice, the banner, the glow, and the status line |
| Session lifecycle | `app/modular_agent.py` | Fixed greeting, three words to interrupt, farewell, time limits |

## Prerequisites

- **A Vonage account** and the [Vonage CLI](https://github.com/Vonage/vonage-cli)
  3.3.1 or newer (`npm install -g @vonage/cli`), to create the Video application.
- **A Deepgram API key** from the [Deepgram Console](https://console.deepgram.com).
- **An OpenAI API key** with API billing set up, from
  [platform.openai.com/api-keys](https://platform.openai.com/api-keys). A ChatGPT
  subscription does not include API credits.
- **An ElevenLabs account on a paid plan** (Starter or above), and an API key from
  [ElevenLabs API keys](https://elevenlabs.io/app/developers/api-keys) with the
  **Text to Speech** permission.
- **Docker** with Docker Compose v2 (Docker Desktop on macOS/Windows).
- A current **Chrome, Edge, Firefox, or Safari** and a microphone. Headphones help.
- **Outbound network access** from the container to Vonage (HTTPS plus WebRTC media),
  `api.deepgram.com`, `api.openai.com`, and `api.elevenlabs.io`.

All four services bill per use; see [Limitations and costs](#limitations-and-costs).

## Setup

```bash
git clone https://github.com/Vonage-Community/blog-video-python_pipecat-dinner_with_da_vinci.git
cd blog-video-python_pipecat-dinner_with_da_vinci
```

### 1. Create the Vonage application

Authenticate the CLI with the API key and secret from the
[Vonage API Dashboard](https://dashboard.vonage.com), then create the application.
`--private-key-file` saves its private key straight into `secrets/`:

```bash
vonage auth set --api-key='YOUR_API_KEY' --api-secret='YOUR_API_SECRET'
vonage apps create "Dinner With da Vinci" --private-key-file ./secrets/private.key
```

Copy the **Application ID** from the output, then turn on Video for it:

```bash
vonage apps capabilities update <APPLICATION_ID> video > /dev/null
vonage apps show <APPLICATION_ID>
```

At the time of writing, Vonage CLI 3.3.1 prints your stored credentials when it
updates the Video capability, so the command discards its output (errors still
show). `vonage apps show` confirms the application now lists `VIDEO`.

### 2. Design his voice

In the ElevenLabs app, open **Voices → My Voices → Add a new voice → Voice Design** and
describe the voice. This is the description used to build the sample:

```text
A warm, thoughtful man in his late sixties, speaking English with a natural Italian
accent. Measured pace, gentle humor, curious, as if talking across a candlelit dinner
table. Clear and unhurried, never theatrical.
```

Pick the preview you like, save it, then copy its voice ID (the voice's menu → **Copy
voice ID**). The description never names Leonardo: it describes a character. Don't
clone or imitate a real person's voice.

The same voice speaks Italian: the app uses ElevenLabs' multilingual Flash v2.5 model.

### 3. Configure the app

```bash
cp .env.example .env
```

Edit `.env` and set the application ID, the three provider keys, and the voice ID:

```dotenv
VONAGE_APPLICATION_ID=your-application-id
DEEPGRAM_API_KEY=your-deepgram-key
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=sk_...
ELEVENLABS_VOICE_ID=your-designed-voice-id
```

### 4. Set the private key's permissions

```bash
chmod 700 secrets
chmod 644 secrets/private.key
```

`chmod 700` keeps other users on your machine out of the folder, and `chmod 644` lets
the container's unprivileged user read the key. `secrets/` is ignored by Git and
excluded from the Docker build. Compose mounts the key read-only into the container.

## Run

```bash
docker compose up --build
```

The first build downloads Python dependencies and takes a few minutes. When it's
ready you'll see a line starting `Ready: agent=Deepgram nova-3-general -> OpenAI
gpt-4.1 -> ElevenLabs eleven_flash_v2_5`. If any setting is missing, the server still
starts and lists what to fix, in the logs and on the page.

Open **<http://localhost:8000>**, choose a language, click **Join the dinner**, and allow
microphone access. Stop the server with `Ctrl-C` (or `docker compose down`).

No tunnel is needed: the app runs on `localhost` and receives no webhooks. Browsers only
allow microphone access on `localhost` or HTTPS, so opening it from another device
needs HTTPS.

## Test

[docs/PERSONA_TEST.md](docs/PERSONA_TEST.md) lists questions to ask him, in both
languages, and what a good answer does. The short version:

- [ ] The page shows the AI-portrayal notice before you join, and the banner during the call.
- [ ] He opens with the fixed greeting, which says he's an AI portrayal.
- [ ] Ask "Are you the real Leonardo?" He says plainly that he's an AI portrayal.
- [ ] Ask for his most famous quote. He doesn't present any saying as his exact words.
- [ ] Ask about the telescope. He doesn't know it (it's from 1608).
- [ ] Tell him about airplanes. He asks how they work instead of explaining them.
- [ ] Say "okay" while he talks: he keeps going. Say a full sentence: he stops.
- [ ] Stay quiet for two minutes: he says goodnight and the call ends.
- [ ] Pick **Italiano**: the greeting, his replies, and the banner are in Italian.

`AGENT_MODE=echo` checks the Vonage audio path without any AI provider: you hear a
beep, then your own voice.

Automated tests (Linux container, no credentials needed):

```bash
docker build --target test -t dinner-with-da-vinci:test .
```

## Configuration

All settings live in `.env`; [`.env.example`](.env.example) documents each one.

| Variable | Default | Purpose |
|---|---|---|
| `VONAGE_APPLICATION_ID` | (required) | Vonage application ID (UUID) with Video enabled |
| `VONAGE_PRIVATE_KEY_FILE` | `./secrets/private.key` | Host path of the private key |
| `DEEPGRAM_API_KEY` | (required) | Deepgram API key |
| `DEEPGRAM_MODEL` | `nova-3-general` | Deepgram streaming model |
| `DEEPGRAM_LANGUAGE` | `en` | Starting language: `en` or `it` |
| `DEEPGRAM_KEYTERMS` | (empty) | Names Deepgram might mishear, for example `Melzi,Sforza,Verrocchio` |
| `OPENAI_API_KEY` | (required) | OpenAI API key |
| `OPENAI_MODEL` | `gpt-4.1` | Chat model that writes his replies |
| `OPENAI_MODELS` | `gpt-4.1,gpt-4.1-mini` | Models the behind-the-scenes panel offers |
| `ELEVENLABS_API_KEY` | (required) | ElevenLabs API key (paid plan) |
| `ELEVENLABS_VOICE_ID` | (required) | Your Voice Design voice |
| `ELEVENLABS_MODEL` | `eleven_flash_v2_5` | Multilingual text-to-speech model |
| `ELEVENLABS_VOICES` | (empty) | Extra voices the panel may offer, as `VOICE_ID:Name;…` |
| `AGENT_MODE` | `modular` | `echo` is a no-provider diagnostic |
| `MAX_ACTIVE_SESSIONS` | `1` | Concurrent sessions (1 to 5) |
| `MAX_SESSION_SECONDS` | `600` | Hard limit per dinner |
| `IDLE_TIMEOUT_SECONDS` | `120` | Silence before he says goodnight |
| `READY_TIMEOUT_SECONDS` | `60` | Ends a session if the browser never becomes ready |
| `SESSION_CREATES_PER_MINUTE` | `6` | Rate limit on starting sessions |
| `LOG_LEVEL` | `INFO` | `DEBUG` also enables the native connector's own, unredacted logs |
| `LOG_TRANSCRIPTS` | `false` | Also write what both sides say to the server logs |
| `PORT` | `8000` | Port on `127.0.0.1` where the page is served |

The behind-the-scenes panel on the join screen changes the model, voice speed,
keyterms, and turn-taking for one call. There's deliberately no box for extra
instructions: the persona's rules are fixed on the server, and the server rejects
instructions, unlisted voices, and other languages.

## Build your own character

Everything about him lives in [`app/persona.py`](app/persona.py): the scene and cutoff,
the personality, the rules, the greeting, farewell, disclosure, and banner in each
language, and the portrait credit. Change that file, the portrait in `web/images/`,
and the voice, and the rest of the app stays the same. Keep the rules about being an AI
and about quotes, and check the rights to any name, image, and voice you use.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Page says **The server is not configured yet** | Fix each listed item in `.env` (or `secrets/`), then restart. |
| `ELEVENLABS_VOICE_ID must be the 20-character ID…` | Paste the ID of the voice you designed, not its name. |
| **Text-to-speech (ElevenLabs) failed** | Check that the voice is in the same account as the key, that the account is on a paid plan, and that the key has Text to Speech. |
| `Cannot read the Vonage private key … permission denied` | Run `chmod 644 secrets/private.key` (keep `chmod 700 secrets`). |
| **Vonage rejected the credentials (401)** | `VONAGE_APPLICATION_ID` and `private.key` must come from the same application. |
| **Vonage refused the request (403)** | Turn on Video: `vonage apps capabilities update <APPLICATION_ID> video > /dev/null`. |
| Deepgram mishears names (Sforza, Melzi, Milan) | Add them to `DEEPGRAM_KEYTERMS` and restart. Keyterms are a small per-minute add-on. |
| He interrupts himself | Use headphones; he hears your speakers otherwise. |
| `ModuleNotFoundError: vonage_video_connector` | The connector ships Linux wheels only; use `docker compose up`. |
| **Microphone access is blocked** | Allow the microphone in the browser's site settings, and use `http://localhost:8000`. |
| **Your browser blocked audio playback** | Click **Enable audio**. |
| `Bind for 127.0.0.1:8000 failed: port is already allocated` | Set `PORT=8001` in `.env` and open `http://localhost:8001`. |

## Limitations and costs

- **A portrayal, not a historian.** The prompt fixes the scene and asks him not to
  invent quotes, settle disputed facts, or make up gossip. A model follows that well,
  not perfectly: he can still get a detail wrong. The disclosure is what the code
  guarantees.
- **A local demo, not a production service.** There are no user accounts, so Compose
  binds the port to `127.0.0.1`. ElevenLabs' and OpenAI's usage policies apply to what
  you build with this; ElevenLabs, for example, doesn't allow apps aimed at under-18s
  without its approval.
- **You pay for usage, with four accounts.** Vonage Video bills per participant-minute,
  Deepgram bills audio time, OpenAI bills tokens, and ElevenLabs bills characters. The
  defaults cap a dinner at 10 minutes and one at a time.
- **Nothing is recorded.** The app stores no audio, video, or transcripts.
- **He only listens.** He doesn't see your camera, and his portrait doesn't move.
- **Two workarounds, at the time of writing:**
  - The Vonage transport hands audio to the native connector faster than it plays, so
    Pipecat thinks he has stopped talking while you still hear him. `pace_audio_to_real_time`
    in `app/modular_agent.py` waits for each chunk's playing time, so the three-word
    interruption rule and the farewell timer follow what you hear.
  - Fixed lines are sent to ElevenLabs a sentence at a time. Sent whole, the Italian
    greeting came back as 87 seconds of audio that trailed off into noise.

## Cleanup

```bash
docker compose down --rmi local
vonage apps delete <APPLICATION_ID>
```

Delete the designed voice in ElevenLabs if you don't want to keep it, and revoke the
provider keys if you created them only for this sample.

## Project layout

```text
app/persona.py         the character: scene, cutoff, rules, greeting, farewell, disclosure
app/modular_agent.py   the Pipecat pipeline, the fixed lines, and audio pacing
app/main.py            FastAPI routes, including GET /api/persona
app/call_options.py    what the join screen may change, and how the server checks it
app/config.py          settings from .env, validation, log redaction
app/video_sessions.py  Vonage routed session and per-participant tokens
app/session_manager.py sessions, limits, timeouts, transcript signals
app/agent_process.py   one process per agent
web/                   the page, its script and styles, and the portrait
tests/                 unit and integration tests (no network needed)
docs/                  persona test questions, manual test plan, dependency notes
```

## Related reading (optional)

- Blog post: *Dinner With da Vinci: Build an AI Persona With Vonage Video* (link
  coming when it's published)
- [blog-video-python_pipecat-modular_voice_agent](https://github.com/Vonage-Community/blog-video-python_pipecat-modular_voice_agent):
  the same pipeline as a general voice agent. You don't need it to run this one.
- [blog-video-python_pipecat-openai_realtime_agent](https://github.com/Vonage-Community/blog-video-python_pipecat-openai_realtime_agent):
  a voice agent on one OpenAI Realtime speech-to-speech model.
- [Vonage Video Transport for Pipecat](https://developer.vonage.com/en/video/guides/vonage-video-connector-pipecat-transport)
  and the [Pipecat documentation](https://docs.pipecat.ai)

## License, privacy and attributions

[MIT](LICENSE), except the portrait. This repository started from a copy of
[blog-video-python_pipecat-modular_voice_agent](https://github.com/Vonage-Community/blog-video-python_pipecat-modular_voice_agent)
(MIT, © Vonage). Pipecat is BSD-2-Clause, © Daily. The Vonage Video Web SDK and Video
Connector are used under [Vonage's terms](https://www.vonage.com/legal/communications-apis/terms-of-use/).

**Portrait:** `web/images/leonardo-da-vinci-melzi-portrait.jpg` is *A portrait of
Leonardo*, attributed to Francesco Melzi, c. 1515 to 1518, Royal Collection Trust,
reproduced from [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:A_portrait_of_Leonardo,_by_Francesco_Melzi.jpg),
where it is in the public domain. It isn't covered by the MIT license.

**Privacy:** during a call your microphone audio travels through Vonage Video to the
agent container and on to Deepgram. The conversation's text goes to OpenAI, and his
replies to ElevenLabs. Each provider's API data policies apply. This app keeps
nothing after the call ends.

**AI disclosure:** the character, his words, and his voice are AI-generated. He is not
Leonardo da Vinci, and nothing he says is a quotation.
