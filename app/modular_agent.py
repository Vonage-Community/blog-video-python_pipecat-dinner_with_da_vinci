"""The AI participant: AI da Vinci, a modular Pipecat pipeline in a Vonage Video session.

    Vonage Video session (routed)
        │  your microphone audio
        ▼
    VonageVideoConnectorTransport.input()
        ▼
    MicrophoneGate          drops your audio until the browser can hear the agent
        ▼
    DeepgramSTTService      speech-to-text: your words as text
        ▼
    user aggregator         decides your turn is over (Silero VAD + Smart Turn v3)
        ▼
    OpenAILLMService        writes a text reply from the conversation so far
        ▼
    ElevenLabsTTSService    text-to-speech: the reply in the voice you picked
        ▼
    VonageVideoConnectorTransport.output()
        │  the agent's voice, published as a Vonage stream
        ▼
    assistant aggregator    adds what the agent actually said to the conversation

Each stage is a separate service with its own key, model, and settings. The browser
never talks to any of them directly: every sound reaches you through Vonage Video.

Who the agent plays, and in which language, comes from app/persona.py.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import numpy as np
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    EndFrame,
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    TTSSpeakFrame,
)
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.llm_service import LLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.simli.video import SimliVideoService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.vonage.video_connector import (
    VonageVideoConnectorTransport,
    VonageVideoConnectorTransportParams,
)
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.errors import ErrorCategory
from pipecat.workers.runner import WorkerRunner

from app import persona
from app.config import Settings, redact
from app.session_manager import AgentConnection, AgentEvents

# The pipeline's own idle timeout is a backstop: the farewell (see ModularAgent) ends
# an idle call first, this many seconds earlier.
FAREWELL_HEADSTART_SECONDS = 30


# The avatar's video: square, the smallest size Simli makes larger than its 512 minimum
# that still looks sharp in the portrait frame.
AVATAR_VIDEO_SIZE = 768

# How much of the agent's audio to hand the Vonage connector ahead of time, so playback
# never runs dry between chunks.
AUDIO_LEAD_SECONDS = 0.2


def pace_audio_to_real_time(transport: VonageVideoConnectorTransport) -> None:
    """Hand the agent's audio to the Vonage connector at playing speed.

    At the time of writing, the transport hands each chunk over at once and the native
    connector buffers it, so Pipecat thinks the agent stopped talking about a second
    into each reply, while you still hear it. See the README.
    """
    output = transport.output()
    write = output.write_audio_frame  # type: ignore[attr-defined]
    play_until = 0.0

    async def paced_write(frame: OutputAudioRawFrame) -> bool:
        nonlocal play_until
        play_until = max(play_until, time.monotonic())
        written = await write(frame)
        play_until += len(frame.audio) / (2 * frame.num_channels * frame.sample_rate)
        await asyncio.sleep(max(0.0, play_until - time.monotonic() - AUDIO_LEAD_SECONDS))
        return written

    output.write_audio_frame = paced_write  # type: ignore[attr-defined]


def fixed_speech(text: str) -> list[TTSSpeakFrame]:
    """Words spoken exactly as written, which talking over can't cut short.

    The LLM never sees a request to write them, so it can't leave anything out. They are
    still added to the conversation, so the model knows what was said.

    One frame per sentence, the way the LLM's replies reach ElevenLabs. In testing, Flash
    v2.5 turned the whole Italian greeting, sent at once, into 87 seconds of audio that
    trailed off into noise; sentence by sentence it was 20 seconds and clean.
    """
    frames = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        frame = TTSSpeakFrame(sentence, append_to_context=True)
        frame.interruptible = False
        frames.append(frame)
    return frames


def connection_role(client: dict[str, Any]) -> str | None:
    """Read the role our server put in the token's connection data."""
    try:
        data = json.loads(client.get("connectionData") or "{}")
    except (TypeError, ValueError):
        return None
    return data.get("role") if isinstance(data, dict) else None


class VonageAgent:
    """Runs one Pipecat pipeline inside one Vonage Video session.

    Subclasses build the pipeline. This base class wires up the Vonage transport
    events, the session lifecycle, and stopping.
    """

    def __init__(self, settings: Settings, connection: AgentConnection, events: AgentEvents):
        self._settings = settings
        self._connection = connection
        self._events = events
        self._runner: WorkerRunner | None = None
        self._worker: PipelineWorker | None = None
        self._stop_requested = False
        self._conversation_requested = False
        self._conversation_started = False
        self._joined = False
        self._failure_reported = False
        self._said_farewell = False

    def build_pipeline(self, transport: VonageVideoConnectorTransport) -> PipelineWorker:
        raise NotImplementedError

    async def begin_conversation(self, worker: PipelineWorker) -> None:
        raise NotImplementedError

    async def run(self) -> None:
        """Join the session and run until stopped, idle, or failed."""
        if self._stop_requested:
            return

        transport = VonageVideoConnectorTransport(
            self._connection.application_id,
            self._connection.session_id,
            self._connection.token,
            VonageVideoConnectorTransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                # With a Simli face set, he's a talking portrait; without one, the browser
                # shows the same illustration as a still image.
                video_out_enabled=bool(self._settings.simli_face_id),
                video_out_is_live=True,
                video_out_width=AVATAR_VIDEO_SIZE,
                video_out_height=AVATAR_VIDEO_SIZE,
                # The browser shows this name next to the agent's stream.
                publisher_name=persona.DISPLAY_NAME,
                # Subscribe to every audio stream in the session. Only the browser
                # holds the other token, so that is the user's microphone.
                audio_in_auto_subscribe=True,
                # The native SDK logs straight to stderr, bypassing our redaction.
                video_connector_log_level="INFO" if self._settings.log_level == "DEBUG" else "WARN",
            ),
        )
        self._register_transport_events(transport)
        pace_audio_to_real_time(transport)

        worker = self.build_pipeline(transport)
        self._register_worker_events(worker)
        self._worker = worker
        if self._conversation_requested:
            await self._begin_once()

        runner = WorkerRunner(handle_sigint=False)
        self._runner = runner

        @runner.event_handler("on_ready")
        async def on_ready(runner: WorkerRunner) -> None:
            # stop() may have been called while the runner was starting.
            if self._stop_requested:
                await runner.cancel(reason="session ended")

        await runner.add_workers(worker)
        await runner.run()

        if self._said_farewell:
            # The farewell played and the pipeline ended itself. Tell the server why.
            self._events.idle_timeout()
        # Safety net: never end silently without having joined.
        elif not self._joined and not self._stop_requested:
            self._report_failure(
                "The agent stopped before it joined the Vonage session. See the server logs."
            )

    async def start_conversation(self) -> None:
        """Called once the browser has subscribed to the agent and can play its audio."""
        self._conversation_requested = True
        if self._worker is not None:
            await self._begin_once()

    async def stop(self) -> None:
        """Leave the Vonage session and close provider connections. Idempotent."""
        self._stop_requested = True
        if self._runner is not None:
            await self._runner.cancel(reason="session ended")

    def _report_failure(self, message: str) -> None:
        if not self._failure_reported:
            self._failure_reported = True
            self._events.agent_failed(message)

    async def _begin_once(self) -> None:
        if self._conversation_started or self._worker is None:
            return
        self._conversation_started = True
        await self.begin_conversation(self._worker)

    def _register_transport_events(self, transport: VonageVideoConnectorTransport) -> None:
        @transport.event_handler("on_joined")
        async def on_joined(transport: VonageVideoConnectorTransport, data: dict) -> None:
            logger.info("Agent joined the Vonage Video session")
            self._joined = True
            self._events.agent_joined()

        @transport.event_handler("on_participant_joined")
        async def on_participant_joined(transport: VonageVideoConnectorTransport, client: dict):
            role = connection_role(client) or "unknown"
            logger.info(f"Stream {client['streamId']} received from a '{role}' participant")

        # Fires when the agent's subscription to a stream is connected, i.e. it
        # can now hear that participant.
        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport: VonageVideoConnectorTransport, client: dict):
            if connection_role(client) == "user":
                logger.info("Agent is receiving the user's audio")
                self._events.user_audio_connected()

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport: VonageVideoConnectorTransport, client: dict):
            if connection_role(client) == "user":
                logger.info("The user's stream left the session")
                self._events.user_left()

        @transport.event_handler("on_error")
        async def on_error(transport: VonageVideoConnectorTransport, description: str) -> None:
            self._report_failure(f"Vonage Video Connector error: {description}")

    def _register_worker_events(self, worker: PipelineWorker) -> None:
        @worker.event_handler("on_pipeline_error")
        async def on_pipeline_error(worker: PipelineWorker, frame: ErrorFrame) -> None:
            stage = failed_stage(frame)
            # Services retry dropped connections on their own. Only end the session
            # when a service says it can't continue (a bad key, an unknown model or
            # voice, no credit), so the browser shows why instead of a silent agent.
            # An avatar that can't connect swallows his voice, so it always ends the call.
            recoverable = frame.processor is None or frame.processor.is_usable
            if not frame.fatal and recoverable and stage != "Avatar (Simli)":
                logger.warning(f"{stage} reported a recoverable error: {redact(frame.error)}")
                return
            self._report_failure(describe_failure(stage, frame))
            if self._runner is not None:
                await self._runner.cancel(reason="pipeline error")

        @worker.event_handler("on_setup_timeout")
        async def on_setup_timeout(worker: PipelineWorker) -> None:
            # Connecting to Vonage or a provider hung (a firewall that drops packets,
            # for example). The worker stops itself after this.
            self._report_failure(
                "Timed out connecting to Vonage Video and the AI services. Check that the "
                "container can reach Vonage, Deepgram, OpenAI, and ElevenLabs."
            )

        @worker.event_handler("on_idle_timeout")
        async def on_idle_timeout(worker: PipelineWorker) -> None:
            # PipelineWorker cancels itself and the runner after this.
            self._events.idle_timeout()


# --- Which stage failed? -------------------------------------------------------------

# What to check for each stage, by the error category Pipecat reports.
_HINTS: dict[str, dict[ErrorCategory, str]] = {
    "Speech-to-text (Deepgram)": {
        ErrorCategory.AUTHENTICATION: "Check DEEPGRAM_API_KEY.",
        ErrorCategory.INVALID_REQUEST: "Check DEEPGRAM_MODEL and DEEPGRAM_LANGUAGE.",
        ErrorCategory.QUOTA: "Your Deepgram account is out of credit.",
    },
    "LLM (OpenAI)": {
        ErrorCategory.AUTHENTICATION: "Check OPENAI_API_KEY.",
        ErrorCategory.INVALID_REQUEST: "Check OPENAI_MODEL.",
        ErrorCategory.QUOTA: "Your OpenAI API account is out of credit.",
    },
    "Avatar (Simli)": {
        ErrorCategory.AUTHENTICATION: "Check SIMLI_API_KEY.",
        ErrorCategory.INVALID_REQUEST: "Check SIMLI_FACE_ID.",
        ErrorCategory.QUOTA: "Your Simli account is out of minutes.",
    },
    "Text-to-speech (ElevenLabs)": {
        ErrorCategory.AUTHENTICATION: "Check ELEVENLABS_API_KEY.",
        ErrorCategory.AUTHORIZATION: (
            "ElevenLabs refused this voice. Check that ELEVENLABS_VOICE_ID is a voice in "
            "this account and that the account is on a paid plan."
        ),
        ErrorCategory.INVALID_REQUEST: "Check ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL.",
        ErrorCategory.QUOTA: "Your ElevenLabs account is out of credits.",
    },
}


def failed_stage(frame: ErrorFrame) -> str:
    """Name the pipeline stage an error came from."""
    processor = frame.processor
    if isinstance(processor, STTService):
        return "Speech-to-text (Deepgram)"
    if isinstance(processor, LLMService):
        return "LLM (OpenAI)"
    if isinstance(processor, TTSService):
        return "Text-to-speech (ElevenLabs)"
    if isinstance(processor, SimliVideoService):
        return "Avatar (Simli)"
    return "Vonage Video"


# Provider SDKs put the full request headers in some errors. They're noise on the page.
_HEADERS = re.compile(r"headers: \{.*?\},?\s*")


def describe_failure(stage: str, frame: ErrorFrame) -> str:
    hint = _HINTS.get(stage, {}).get(frame.category, "") if frame.category else ""
    # When an ElevenLabs account runs out of credits, its WebSocket sends no audio and
    # Pipecat only sees silence, so the error doesn't say why.
    if stage == "Text-to-speech (ElevenLabs)" and "no audio" in frame.error and not hint:
        hint = (
            "This usually means the ElevenLabs account is out of credits: check its usage "
            "page. The free plan has 10,000 credits a month."
        )
    error = _HEADERS.sub("", redact(frame.error))
    return " ".join(part for part in (f"{stage} failed: {error}", hint) if part)


# Which pipeline stage each part of Pipecat's latency breakdown belongs to.
_STAGE_OF_CONTRIBUTION = {
    "endpointing wait": "Turn-taking",
    "turn detection": "Turn-taking",
    "transcription": "Deepgram",
    "LLM inference": "OpenAI",
    "sentence aggregation": "OpenAI",  # waiting for OpenAI to finish a sentence
    "turn completion": "OpenAI",
    "speech synthesis": "ElevenLabs",
}
STAGE_ORDER = ("Turn-taking", "Deepgram", "OpenAI", "ElevenLabs", "Other")


def stage_latency(breakdown: Any) -> tuple[list[dict[str, Any]], float]:
    """Sum one reply's latency breakdown by pipeline stage, in pipeline order."""
    totals: dict[str, float] = {}
    for part in breakdown.contributions:
        stage = _STAGE_OF_CONTRIBUTION.get(part.label, "Other")
        totals[stage] = totals.get(stage, 0.0) + part.duration_secs
    stages = [
        {"stage": stage, "secs": round(totals[stage], 3)}
        for stage in STAGE_ORDER
        if totals.get(stage, 0.0) >= 0.005
    ]
    return stages, round(breakdown.total_secs, 3)


class MicrophoneGate(FrameProcessor):
    """Drops microphone audio until the browser can hear the agent.

    Nothing reaches Deepgram (or costs anything) before then, so the agent can't
    answer something you said before it greeted you.
    """

    def __init__(self) -> None:
        super().__init__()
        self.open = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and not self.open:
            return
        await self.push_frame(frame, direction)


class ModularAgent(VonageAgent):
    """Deepgram speech-to-text -> OpenAI LLM -> ElevenLabs text-to-speech."""

    def build_pipeline(self, transport: VonageVideoConnectorTransport) -> PipelineWorker:
        settings = self._settings
        assert settings.deepgram_api_key and settings.openai_api_key
        assert settings.elevenlabs_api_key

        self._gate = MicrophoneGate()

        # Listen: streaming transcription of the user's microphone.
        stt = DeepgramSTTService(
            api_key=settings.deepgram_api_key.get(),
            settings=DeepgramSTTService.Settings(
                model=settings.deepgram_model,
                language=settings.deepgram_language,
                # Keyterm prompting: boost words Deepgram would otherwise mishear.
                keyterm=list(settings.deepgram_keyterms) or None,
            ),
        )

        # Think: a reply in character, from the whole conversation so far. The persona's
        # rules and the language for this call come from app/persona.py.
        llm = OpenAILLMService(
            api_key=settings.openai_api_key.get(),
            settings=OpenAILLMService.Settings(
                model=settings.openai_model,
                system_instruction=persona.system_instruction(
                    settings.deepgram_language, settings.guest_name
                ),
            ),
        )

        # Speak: stream the reply's sentences to ElevenLabs as they arrive.
        tts = ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key.get(),
            settings=ElevenLabsTTSService.Settings(
                model=settings.elevenlabs_model,
                voice=settings.elevenlabs_voice_id,
                speed=settings.elevenlabs_speed,
                # The same voice speaks both languages. Naming the language helps it read
                # numbers and dates the way that language says them.
                language=settings.deepgram_language,
            ),
        )

        # Memory: the context holds the whole dinner, every turn from both sides, for the
        # length of the call. Nothing in it is saved anywhere when the call ends.
        context = LLMContext()
        # No speech-to-speech model decides when you've finished talking anymore, so
        # the user aggregator does: Silero VAD hears speech start and stop, and
        # Pipecat's default Smart Turn v3 model decides whether the sentence is done.
        # Both run locally on the CPU. stop_secs is the silence before Smart Turn
        # decides; longer means fewer interruptions of you, and slower replies.
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=settings.vad_stop_secs)),
                user_turn_strategies=UserTurnStrategies(
                    # While the agent talks, it only stops once Deepgram has heard this
                    # many of your words, so "okay" or "mm-hm" doesn't cut it off.
                    start=[MinWordsUserTurnStartStrategy(min_words=settings.interrupt_min_words)],
                ),
                # How long the guest can stay quiet after he finishes speaking.
                user_idle_timeout=settings.idle_timeout_seconds,
            ),
        )

        # A long silence: he says goodbye in character, then the call ends.
        @user_aggregator.event_handler("on_user_turn_idle")
        async def on_user_idle(aggregator: Any) -> None:
            await self._say_farewell()

        # The text between the stages: what Deepgram heard, and what the agent said.
        # Both go to your browser's transcript panel; logging them is optional.
        @user_aggregator.event_handler("on_user_turn_message_added")
        async def on_user_message(aggregator: Any, message: Any) -> None:
            self._send_transcript("user", message.content)

        @assistant_aggregator.event_handler("on_assistant_turn_stopped")
        async def on_assistant_message(aggregator: Any, message: Any) -> None:
            # Built from ElevenLabs' word timestamps, so after an interruption it holds
            # only the words that played.
            self._send_transcript("agent", message.content, interrupted=message.interrupted)

        # Logs, for each reply, how long you waited and which stage the time went to.
        latency = UserBotLatencyObserver()

        @latency.event_handler("on_latency_breakdown")
        async def on_latency_breakdown(observer: Any, breakdown: Any) -> None:
            logger.info("Latency: " + " | ".join(breakdown.turn_contribution_lines()))
            stages, total = stage_latency(breakdown)
            self._events.latency(stages, total)

        # Optional: Simli turns his voice into a talking portrait, video and voice in sync.
        avatar = [self._avatar()] if settings.simli_face_id else []

        pipeline = Pipeline(
            [
                transport.input(),
                self._gate,
                stt,
                user_aggregator,
                llm,
                tts,
                *avatar,
                transport.output(),
                assistant_aggregator,
            ]
        )
        return PipelineWorker(
            pipeline,
            params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
            observers=[latency],
            idle_timeout_secs=settings.idle_timeout_seconds + FAREWELL_HEADSTART_SECONDS,
            processor_unusable_policy=ProcessorUnusablePolicy.END,
            # The browser follows the call through Vonage events, not Pipecat's RTVI protocol.
            enable_rtvi=False,
        )

    def _avatar(self) -> SimliVideoService:
        settings = self._settings
        assert settings.simli_api_key
        return SimliVideoService(
            api_key=settings.simli_api_key.get(),
            face_id=settings.simli_face_id,
            # Simli ends its own session too, so it can't outlive the dinner.
            max_session_length=settings.max_session_seconds,
            max_idle_time=settings.idle_timeout_seconds + FAREWELL_HEADSTART_SECONDS,
            framing=SimliVideoService.Framing(
                streaming_width=AVATAR_VIDEO_SIZE, streaming_height=AVATAR_VIDEO_SIZE
            ),
        )

    def _send_transcript(self, role: str, text: str, interrupted: bool = False) -> None:
        if not text.strip():
            return
        if self._settings.log_transcripts:
            logger.info(f"Transcript {role}: {text}" + (" (interrupted)" if interrupted else ""))
        self._events.transcript(role, text, interrupted)

    async def begin_conversation(self, worker: PipelineWorker) -> None:
        logger.info("Browser is ready: opening the microphone and playing the greeting")
        self._gate.open = True
        # The disclosure is guaranteed in code, not left to the model: every call opens
        # with these exact words, before the LLM has said anything.
        greeting = persona.greeting(self._settings.deepgram_language, self._settings.guest_name)
        await worker.queue_frames(fixed_speech(greeting))

    async def _say_farewell(self) -> None:
        if self._said_farewell or self._worker is None:
            return
        self._said_farewell = True
        logger.info("The guest has been quiet too long: saying goodbye")
        farewell = persona.LANGUAGES[self._settings.deepgram_language].farewell
        # EndFrame waits behind the farewell's audio, so the pipeline ends after it plays.
        await self._worker.queue_frames([*fixed_speech(farewell), EndFrame()])


class MicrophoneEcho(FrameProcessor):
    """Turns incoming microphone audio into outgoing audio once enabled."""

    def __init__(self) -> None:
        super().__init__()
        self.enabled = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if self.enabled and isinstance(frame, InputAudioRawFrame):
            await self.push_frame(
                OutputAudioRawFrame(
                    audio=frame.audio,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                )
            )
        await self.push_frame(frame, direction)


def beep(seconds: float = 0.6, hz: float = 440.0, sample_rate: int = 24000) -> OutputAudioRawFrame:
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    samples = (0.3 * 32767 * np.sin(2 * np.pi * hz * t)).astype(np.int16)
    return OutputAudioRawFrame(audio=samples.tobytes(), sample_rate=sample_rate, num_channels=1)


class EchoAgent(VonageAgent):
    """Diagnostic mode (AGENT_MODE=echo): no AI providers, no cost beyond Vonage.

    Plays a beep when the browser is ready, then echoes your microphone back.
    Hearing both proves audio flows in each direction through Vonage Video.
    """

    def build_pipeline(self, transport: VonageVideoConnectorTransport) -> PipelineWorker:
        self._echo = MicrophoneEcho()
        pipeline = Pipeline([transport.input(), self._echo, transport.output()])
        return PipelineWorker(
            pipeline,
            idle_timeout_secs=self._settings.idle_timeout_seconds,
            processor_unusable_policy=ProcessorUnusablePolicy.END,
            enable_rtvi=False,
        )

    async def begin_conversation(self, worker: PipelineWorker) -> None:
        logger.info("Browser is ready: playing a test beep, then echoing the microphone")
        await worker.queue_frames([beep()])
        self._echo.enabled = True


def create_agent(
    settings: Settings, connection: AgentConnection, events: AgentEvents
) -> VonageAgent:
    if settings.agent_mode == "echo":
        return EchoAgent(settings, connection, events)
    return ModularAgent(settings, connection, events)
