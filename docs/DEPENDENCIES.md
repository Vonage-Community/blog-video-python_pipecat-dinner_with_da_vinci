# Dependencies and verified versions

Everything installs from one manifest (`pyproject.toml`) and one lock file (`uv.lock`).
The Docker image runs `uv sync --frozen`, so a build installs exactly what the lock
says or fails.

## Pinned versions

Versions as installed in the Docker image and printed by `importlib.metadata` inside
the container (2026-11-19, unchanged for this repo on 2026-11-24). Pipecat 1.17.0 came out
on 2026-11-22; it adds AWS Transcribe language identification and a SIP transport,
neither of which this sample uses, so it stays on 1.16.0:

| Component | Version | Source |
|---|---|---|
| Python | 3.12.16 | `python:3.12-slim-bookworm` (Debian 12, glibc 2.36) |
| `pipecat-ai` | 1.16.0 | PyPI, with the `deepgram`, `elevenlabs`, `openai`, and `vonage-video-connector` extras |
| `vonage-video-connector` | 1.0.3 | PyPI, via Pipecat's `vonage-video-connector` extra (Linux only) |
| `deepgram-sdk` | 7.19.0 | PyPI, via Pipecat's `deepgram` extra |
| `openai` | 3.55.1 | PyPI, a Pipecat core dependency |
| ElevenLabs | no SDK | Pipecat's `ElevenLabsTTSService` talks to the WebSocket API with `websockets` 17.4 |
| Silero VAD, Smart Turn v3 | ONNX models inside the `pipecat-ai` wheel | run with `onnxruntime` 1.32.0 on the CPU |
| `vonage` (server SDK) | 4.10.0 | PyPI |
| `fastapi` / `uvicorn` | 0.165.0 / 0.54.0 | PyPI |
| Vonage Video Web SDK | `@vonage/client-sdk-video@2.36.0` | npm via unpkg |
| OS packages | `libexpat1`, `libglib2.0-0` | Debian bookworm; the list Vonage's server samples install |
| uv | 0.11.32 | PyPI, build stage only |

`[tool.uv] exclude-newer = "2026-11-19T00:00:00Z"` keeps re-locking reproducible.

## Provider defaults

| Stage | Default | Why |
|---|---|---|
| Speech-to-text | Deepgram `nova-3-general`, `en` | Pipecat's default for `DeepgramSTTService`. Interim results on, so the user aggregator sees speech early. |
| LLM | OpenAI `gpt-4.1` | Pipecat's default for `OpenAILLMService`, and within the ~700 ms first-token budget in [Pipecat's voice benchmark](https://www.pipecat.ai/benchmarks/voice-readiness). Configurable with `OPENAI_MODEL`. |
| Text-to-speech | ElevenLabs `eleven_flash_v2_5` | Pipecat's default; ElevenLabs recommends Flash for agents (~100 ms). `eleven_v4_turbo` uses the Text to Dialogue WebSocket, which `ElevenLabsTTSService` doesn't use. |
| Voice | None: `ELEVENLABS_VOICE_ID` is required | Each reader designs their own with [Voice Design](https://elevenlabs.io/docs/eleven-creative/voices/voice-design). A designed voice belongs to the account that made it, so there is no ID to ship. |
| Languages | `en`, `it` | The persona is written for both. Deepgram updated its Italian streaming model on 2026-09-22; [Smart Turn v3](https://github.com/pipecat-ai/smart-turn) lists Italian; Flash v2.5 is multilingual. |

## The Pipecat source: PyPI `pipecat-ai`

The [Vonage Video Transport for Pipecat guide](https://developer.vonage.com/en/video/guides/vonage-video-connector-pipecat-transport)
installs `pipecat-ai[vonage-video-connector]` from PyPI. This sample adds the three
service extras to the same requirement, so Pipecat is installed once. Never install
the [Vonage Pipecat fork](https://github.com/Vonage/pipecat) from Git alongside it.

## APIs verified at the pinned version

Read in Pipecat 1.16.0's source and exercised by `tests/test_modular_agent.py` with
the real classes:

- `VonageVideoConnectorTransport(application_id, session_id, token, params)`;
  input defaults to 16 kHz mono and output to 24 kHz mono. Deepgram takes the input
  rate and ElevenLabs the output rate from the pipeline, so there is no manual
  resampling.
- `DeepgramSTTService(api_key=..., settings=DeepgramSTTService.Settings(model, language))`.
  It sends a KeepAlive every 5 seconds, so a closed microphone gate doesn't time out
  the Deepgram connection.
- `OpenAILLMService(api_key=..., settings=OpenAILLMService.Settings(model, system_instruction))`.
- `ElevenLabsTTSService(api_key=..., settings=ElevenLabsTTSService.Settings(model, voice, speed, language))`.
  The `voice_id=` and `model=` constructor arguments are deprecated.
- `TTSSpeakFrame(text, append_to_context=True)` with `frame.interruptible = False`:
  spoken word for word, added to the context, and kept through interruptions.
- `LLMUserAggregatorParams(user_idle_timeout=...)` and the aggregator's
  `on_user_turn_idle` event. The timer starts on `BotStoppedSpeakingFrame`.
- `EndFrame` queued after the farewell: the worker ends once it reaches the end of the
  pipeline, after the farewell's audio.
- `LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()))`.
  With no `user_turn_strategies`, turns start on VAD or a transcript and stop when
  `LocalSmartTurnAnalyzerV3` says the sentence is complete.
- `DeepgramSTTService.Settings(keyterm=[...])`, sent as repeated `keyterm` query
  parameters; Nova-3 only.
- Aggregator events `on_user_turn_message_added` (`message.content`) and
  `on_assistant_turn_stopped` (`message.content`, `message.interrupted`).
- `vonage` 4.10.0: `video.send_signal(session_id, SignalData(type, data))`, which
  signals every connection in the session. Signal data is capped at 8 kB, so lines are
  cut to 2,000 characters.
- `ErrorFrame.processor`, `.category` (`ErrorCategory`), `.fatal`, and
  `FrameProcessor.is_usable`, used to name the failed stage and to decide whether to
  end the session.
- `PipelineWorker`, `WorkerRunner`, `ProcessorUnusablePolicy.END`, and worker events
  `on_pipeline_error`, `on_idle_timeout`, `on_setup_timeout`.

## Where sources disagreed, and what this sample does

| Topic | Sources | Choice |
|---|---|---|
| Where VAD goes | The Vonage transport guide passes `vad_analyzer=SileroVADAnalyzer()` to `VonageVideoConnectorTransportParams`. Pipecat deprecated the transport field, then removed it from `TransportParams`; Pydantic ignores the unknown argument with no warning (checked in the 1.16.0 image). | VAD on `LLMUserAggregatorParams`, as Pipecat's own examples do. |
| Pipeline classes | Older project notes used `PipelineTask` and `OpenAILLMContext`. | `PipelineWorker`, `WorkerRunner`, `LLMContext`. |
| Greeting trigger | Pipecat examples greet in `on_client_connected`. | Greet on the browser's `POST /ready`, because only the browser knows it can play audio. |
| Connector instances | The Video Connector guide allows one connector instance per process. | One OS process per session (`app/agent_process.py`). |
| Routed sessions | Required by the project brief; Kitt Phi's tested tutorial uses routed sessions. | Always routed. |
| When the bot stops speaking | `VonageVideoConnectorOutputTransport.write_audio_frame` calls the native `add_audio`, which buffers and returns at once. A 30-second reply reached the connector in about 1.1 s, and Pipecat logged *Bot stopped speaking* then, while the browser played it for 30 s more (measured 2026-11-24). `MinWordsUserTurnStartStrategy` then saw a silent bot and let one word interrupt, and the idle timer started mid-reply. Pipecat's websocket transports pace with `_write_audio_sleep`. | `pace_audio_to_real_time()` in `app/modular_agent.py` waits for each chunk's playing time, keeping 0.2 s ahead. Afterwards, *Bot stopped speaking* came within a second of the browser's audio ending, and "Okay." no longer interrupted. |
| Long fixed text to Flash v2.5 | The ElevenLabs API returned 87 s of audio for the 290-character Italian greeting in one request (Default voice *Roger*, with or without `language_code`, at speed 0.9 or 1.0); `eleven_multilingual_v2` returned 21 s. Each sentence alone came back at its normal length (2.8 s, 12.5 s, 4.2 s). | `fixed_speech()` sends one `TTSSpeakFrame` per sentence, the way LLM replies arrive. Re-check with the designed voice. |

## Platforms

| Platform | Status |
|---|---|
| Linux arm64 (Docker Desktop on Apple Silicon) | **Verified 2026-11-24:** image builds; ruff, mypy, and pytest pass inside it; headless Chrome calls in English and Italian (fake microphone) play the greeting, a reply, and the farewell. |
| Linux x86_64 | Not verified with this repo. Wheels exist for all dependencies. |
| Windows host | Not verified. Supported through Docker Desktop. |
| Running the agent outside Docker on macOS/Windows | Not supported: the connector ships Linux wheels only. |

## Updating dependencies

1. Change the pin in `pyproject.toml` (and `exclude-newer`), then run `uv lock`.
2. If the Pipecat version changes, re-read the Vonage transport and the Deepgram,
   OpenAI, and ElevenLabs services at the new version, and update the tables above.
3. Run `docker build --target test .` and the full manual test.
4. Ship a new release with a CHANGELOG entry. Never move the `v1.0.0-tutorial` tag.
