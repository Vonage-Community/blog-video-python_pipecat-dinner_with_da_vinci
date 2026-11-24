# Blog notes (for the author, not the published post)

**Working title:** Dinner With da Vinci: Build an AI Persona With Vonage Video

**Status (2026-11-24):** builds and passes its automated tests in Linux Docker.
Headless Chrome calls with a fake microphone, in English and Italian, played the
greeting, one reply, and the farewell, first with a stand-in voice and then with
Benjamin's designed voice (`GyifqDLdBAgexa11MSrB`). **Not verified yet:** a live
conversation with a person, and Daniela's review of the Italian.

## The six layers, and where each lives

| Layer | Code | Teaching point |
|---|---|---|
| Persona | `app/persona.py` `SYSTEM_INSTRUCTION` | Specific traits instead of adjectives: moves between disciplines in one answer, asks questions back, candid about unfinished work |
| Knowledge cutoff | same | A date, and what to do with things he can't know: ask how they work |
| Memory | `LLMContext()` in `ModularAgent.build_pipeline` | Already there; the only decision is what not to keep |
| Voice | Voice Design prompt and preview text (README), `ELEVENLABS_VOICE_ID` | Describe a character, never name the person. Tuscan accent as a historical reference point (born in Vinci, spoke vernacular Tuscan); custom preview text in character shapes the voice; test the saved voice in both languages |
| Honest status | `web/index.html`, `renderLiveStatus` in `web/app.js` | One invitation line, the tag on his frame, the candlelight, "greeting / speaking / thinking / your turn" |
| Session lifecycle | `fixed_speech`, `begin_conversation`, `_say_farewell` | Fixed greeting and farewell are code, not prompt |

## Generic agent vs persona agent

| | Generic (modular agent) | Persona |
|---|---|---|
| Prompt opens with | "You are a friendly AI voice assistant…" | A scene, a date, and a guest from the future |
| Knows about | Everything the model knows | Nothing after spring 1518 |
| Greeting | Written by the LLM from a greeting prompt | Fixed text, spoken word for word |
| Asked for a famous quote | Gives one (a misattributed one) | Won't vouch for any exact words |
| Asked "are you real?" | "I'm an AI model" | "I'm an AI portrayal, not Leonardo", then back to dinner |
| The browser can add instructions | Yes, after the fixed rules | No |
| Voice | Any library voice | A designed voice, one for both languages |

## Before and after: the invented quote (real output, `gpt-4.1`, 2026-11-24)

- **Generic prompt**, "What's Leonardo da Vinci's most famous quote?": *"One of Leonardo
  da Vinci's most famous quotes is, 'Simplicity is the ultimate sophistication.'"*
  Quote Investigator finds no evidence he wrote it.
- **First persona prompt** still slipped: *"I often wrote of how art is never finished,
  only abandoned"* (usually traced to Paul Valéry). A rule that only said "never quote
  word for word" wasn't enough; it needed "never repeat or paraphrase any famous saying".
- **Final persona prompt**: *"Many sayings are given to me which I may not have spoken
  or written, for people love to put words in the mouths of painters. What I can say is
  that I always believed in the close study of nature, and in letting experience guide
  the mind as much as the books of scholars."*

This is the honest version of the story: the first rule wasn't specific enough, and
testing caught it. See `docs/PERSONA_TEST.md` for the rest.

## Lessons from the build (facts for the post, not Benjamin's experiences)

- **Bot speaking vs what you hear.** The Vonage transport hands audio to the native
  connector, which buffers it. A 30-second reply was handed over in 1.1 s, so Pipecat
  logged "Bot stopped speaking" while the browser played on. Effects: the 3-word
  interrupt rule only applied for that first second (a test "Okay." interrupted the
  reply), and the idle timer counted from the wrong moment. `pace_audio_to_real_time`
  fixed both. **This also affects the modular agent repo**, which has the 3-word rule
  without pacing.
- **Flash v2.5 and long Italian text.** With the stand-in Default voice *Roger*, the
  290-character Italian greeting in one request came back as 87 s of audio that trailed
  off; per sentence it was 20 s. With the designed voice it was a normal 24.7 s either
  way, so it depended on the stand-in voice. Fixed lines went back to one frame each,
  because one frame per sentence broke the Simli avatar mode.
- **Italian replies ran long.** One Italian reply played for 59 s; the length rule
  stated in English didn't carry over. Repeating it in the Italian reply rule fixed it.
- **"Sixteen eighteen."** Spelled-out years can go wrong; the scene now says how to say
  the year.
- **Transcript pieces.** Per-sentence fixed lines arrive as several transcript signals;
  the browser joins back-to-back agent lines into one bubble.
- **Deepgram heard "Sforza in Milan" as "Sforza Emilan".** A keyterms example:
  `DEEPGRAM_KEYTERMS=Sforza,Milan,Melzi`.

## Screenshots for the post

- The invitation: portrait, place card, and the evening's language (take at 1,200 px).
- The table mid-reply: his frame in warm candlelight with the tag, your seat, and Table
  talk open on one exchange and its timing line.
- The Italian dinner: the Italian tag and greeting.
- The before-and-after quote, as two transcript bubbles or a small table.

## Links

- Vonage Video Transport for Pipecat: https://developer.vonage.com/en/video/guides/vonage-video-connector-pipecat-transport
- Pipecat: https://docs.pipecat.ai
- ElevenLabs Voice Design: https://elevenlabs.io/docs/eleven-creative/voices/voice-design
- Quote Investigator, "Simplicity is the ultimate sophistication": https://quoteinvestigator.com/2015/04/02/simple/
- Portrait: an imagined likeness Benjamin illustrated with ChatGPT (`web/images/leonardo-da-vinci-illustrated-dinner.jpg`)
- Simli Trinity-2 faces: https://docs.simli.com/api-reference/trinity-2
- Related, optional: the modular agent post and the OpenAI Realtime post (links once published)
