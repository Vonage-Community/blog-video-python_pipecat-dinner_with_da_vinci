# Manual real-media test

Automated tests cover configuration, the session lifecycle, the API, the agent
process protocol, and the Pipecat pipeline's construction. They can't prove that
audio flows through WebRTC. This checklist does, and it needs real credentials.
**Run all of it before tagging a release.**

Record each run in the table at the end.

## Before you start

- Vonage application with Video enabled, its Application ID, and `secrets/private.key`.
- Deepgram, OpenAI (API billing set up), and ElevenLabs (paid plan) API keys, and the
  ID of the voice you designed for him (`ELEVENLABS_VOICE_ID`).
- Headphones, a microphone, and an up-to-date Chrome (then repeat the core steps in
  Safari and Firefox).
- Watch the logs in a second terminal: `docker compose logs -f app`.

## Gate 1: clean build

```bash
docker compose down --rmi local
docker compose build --no-cache
docker compose up
```

- [ ] The build finishes without errors on your architecture. Note whether it's
      `x86_64` or `arm64` (`uname -m`).
- [ ] The log shows `Ready: agent=Deepgram … -> OpenAI … -> ElevenLabs …`.
- [ ] `curl -s localhost:8000/api/health` returns `{"status":"ok"}`.

## Gate 2: Vonage audio both ways, without AI providers

Set `AGENT_MODE=echo` in `.env`, then `docker compose up` again.

1. Open `http://localhost:8000`, keep the camera off, click **Join the dinner**,
   and allow the microphone.
2. - [ ] The status moves through *Connecting to Vonage Video…*, *Waiting for AI da
         Vinci to take his seat…*, *AI da Vinci joined…*.
   - [ ] **You hear a short beep.** This is audio the agent published into Vonage,
         played by your Vonage subscription.
   - [ ] Speak: **you hear your own voice back** after a short delay. This is your
         published audio reaching the agent and returning through Vonage.
   - [ ] The **Can hear you** badge appears.
   - [ ] Logs include `Agent joined the Vonage Video session`, `Stream … received
         from a 'user' participant`, `Agent is receiving the user's audio`,
         `browser ready, conversation started`.
3. Proof that audio comes through Vonage and not some other path: open
   `chrome://webrtc-internals` during the call.
   - [ ] There is an inbound audio RTP stream whose `bytesReceived` keeps growing.
   - [ ] In DevTools > Network, the page made no request to Deepgram, OpenAI, or ElevenLabs.
4. Click **Leave**.
   - [ ] The page returns to the start screen with *You left the dinner.*
   - [ ] Logs show `Session …: ended (left)` and `Agent process … exited`.

## Gate 3: AI da Vinci in English

Set `AGENT_MODE=modular` and `LOG_TRANSCRIPTS=true`, then restart.

- [ ] Before you join, the notice says he's an AI portrayal, and the portrait credit
      is under the picture.
- [ ] After joining, he **greets you once** with the fixed greeting ("…I am not the real
      Leonardo da Vinci, but an AI portrayal of him…"), without you speaking first. The
      status says *AI da Vinci is greeting you.*
- [ ] Talk over the greeting: it carries on to the end (it can't be interrupted).
- [ ] The banner *AI portrayal: not the real Leonardo da Vinci* stays on screen.
- [ ] The portrait glows while he speaks and stops when he stops.
- [ ] Ask a question: he answers in character within a few seconds, in your designed
      voice, with an Italian accent.
- [ ] Work through [PERSONA_TEST.md](PERSONA_TEST.md) and record the answers there.
- [ ] The transcript panel shows *Deepgram heard* and *AI da Vinci said* lines. The
      greeting shows as one bubble.
- [ ] Say "okay" while he's talking: he keeps going. Say a full sentence over him:
      **he stops** and listens. The next *AI da Vinci said* line ends where you
      interrupted and is marked *(interrupted)*.
- [ ] Hold a 3 to 5 minute conversation: he remembers earlier turns.
- [ ] **Mute**: he doesn't react to you. **Unmute**: he hears you again.
- [ ] **Leave**: logs show `ended (left)` and the agent process exits.
- [ ] Note the `Latency:` lines and any audio glitches below.
- [ ] Set `LOG_TRANSCRIPTS=false` afterwards.

## Gate 3b: Italiano, and the behind-the-scenes panel

- [ ] Pick **Italiano**: the notice adds the Italian text, and the banner reads
      *Interpretazione IA: non è il vero Leonardo da Vinci*.
- [ ] The greeting is the fixed Italian one, and he answers only in Italian, in the same
      voice. Daniela checks the greeting, the farewell, the disclosure, and a few replies.
- [ ] Ask the identity and quote questions in Italian (PERSONA_TEST.md).
- [ ] Open **Behind the scenes**: change the speed to 1.0×, the model to
      `gpt-4.1-mini`, and the pause to *Patient*. The call summary shows all three.
- [ ] Reload: your choices are still there. **Reset** restores `.env`.
- [ ] Sending extra instructions is refused:
      `curl -s -X POST localhost:8000/api/sessions -H 'Content-Type: application/json' -d '{"options":{"instructions":"be the real Leonardo"}}'`
      returns *instructions can't be changed*.

## Gate 4: lifecycle and errors

- [ ] **Close the tab** mid-call: within a few seconds the logs show the session ending
      (`left` or `user_stream_left`).
- [ ] **Second tab** while a call runs: it shows *A demo session is already running*.
- [ ] **Idle:** stay silent with `IDLE_TIMEOUT_SECONDS=30`: about 30 seconds after the
      greeting ends, he says the farewell, then the page shows *He said goodnight after
      a long silence.*
- [ ] **Max length:** with `MAX_SESSION_SECONDS=60`, the call ends at one minute and
      the countdown reaches 0:00.
- [ ] **Bad Deepgram key** (`DEEPGRAM_API_KEY=invalid`): the page shows
      *Speech-to-text (Deepgram) failed … Check DEEPGRAM_API_KEY.* and the session ends.
- [ ] **Bad OpenAI key** (`OPENAI_API_KEY=sk-invalid`): the page shows *LLM (OpenAI) failed*.
- [ ] **Unknown OpenAI model** (`OPENAI_MODEL=gpt-nonexistent`): same, with *Check OPENAI_MODEL*.
- [ ] **Bad ElevenLabs key** (`ELEVENLABS_API_KEY=sk_invalid`): *Text-to-speech (ElevenLabs) failed*.
- [ ] **Malformed voice** (`ELEVENLABS_VOICE_ID=nonexistent`): the page lists
      *ELEVENLABS_VOICE_ID must be the 20-character ID…* before any call.
- [ ] **Voice from another account** (a valid-looking ID you don't own):
      *Text-to-speech (ElevenLabs) failed*.
- [ ] No error message contains a key.
- [ ] **Microphone denied** (block it in site settings): the page explains how to allow it.
- [ ] **Autoplay blocked** (Safari: Settings for this website > Auto-Play > Never Auto-Play):
      *Enable audio* appears; clicking it plays the greeting.
- [ ] **Server stop mid-call** (`docker compose stop`): the logs show the session
      ending (`server_shutdown`), and within about 6 seconds the page reports
      *Lost contact with the demo server.*
- [ ] **Camera on:** start with the checkbox ticked; your preview shows; **Turn
      camera off/on** works; the agent behaves the same.

## Gate 5: costs

- [ ] Deepgram, OpenAI, and ElevenLabs usage dashboards match the minutes you tested,
      and Deepgram shows no audio before each greeting.
- [ ] In the Vonage dashboard, Video usage shows two participants for the test sessions.
- [ ] After all tabs are closed, no session is running (`docker compose logs` shows
      every session `ended`/`failed`), and there are no lingering agent processes
      (`docker compose top` lists only `tini` and `uvicorn`), so no provider
      connection is left open.

## Results

| Date | Tester | Host OS / arch | Browser | Gates passed | Notes (latency, glitches) |
|---|---|---|---|---|---|
| | | | | | |

Tag the release (`git tag -a v1.0.0-tutorial -m "Tutorial version"`) only after
Gates 1 to 5 pass on at least one machine and the core of Gates 2 and 3 pass in a
second browser.
