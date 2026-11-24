// Browser side of Dinner With da Vinci.
//
// 0. The invitation: the AI-portrayal disclosure, the language, and (behind the scenes)
//    how the agent listens, thinks, speaks, and takes turns. The disclosure text comes
//    from the server, the same file the agent's greeting uses. The server checks every
//    choice before it uses it.
// 1. Get microphone (and optional camera) access with the Vonage Video Web SDK.
// 2. Ask our server for a session with those choices. It returns the browser's token only.
// 3. Join the routed Vonage Video session and publish.
// 4. Subscribe to the AI agent's stream, recognized by the role in its
//    connection data, and to nothing else.
// 5. Once its audio can play, tell the server so the agent greets you once.
// 6. Show the transcript signals the server sends: what Deepgram heard, and what
//    the agent said, plus how long each stage took before each reply.
// 7. Keep the AI-portrayal banner on screen, and make the still portrait glow while
//    his audio is playing. Nothing animates his face.
'use strict';

const $ = (id) => document.getElementById(id);
const ui = {
  setup: $('setup'),
  start: $('start'),
  useCamera: $('use-camera'),
  call: $('call'),
  publisher: $('publisher'),
  youPlaceholder: $('you-placeholder'),
  youLevel: $('you-level'),
  mutedBadge: $('muted-badge'),
  agentMedia: $('agent-media'),
  agentLevel: $('agent-level'),
  agentHearing: $('agent-hearing'),
  agentName: $('agent-name'),
  enableAudio: $('enable-audio'),
  mute: $('mute'),
  camera: $('camera'),
  leave: $('leave'),
  timeLeft: $('time-left'),
  stages: $('stages'),
  stagesDetails: $('stages-details'),
  echoNote: $('echo-note'),
  disclosure: $('disclosure'),
  setupPortrait: $('setup-portrait'),
  setupCredit: $('setup-credit'),
  callBanner: $('call-banner'),
  callPortrait: $('call-portrait'),
  callCredit: $('call-credit'),
  agentTile: $('agent-tile'),
  language: $('opt-language'),
  keytermTags: $('keyterm-tags'),
  keytermInput: $('keyterm-input'),
  model: $('opt-model'),
  voice: $('opt-voice'),
  speed: $('opt-speed'),
  speedValue: $('speed-value'),
  pause: $('opt-pause'),
  words: $('opt-words'),
  wordsValue: $('words-value'),
  resetOptions: $('reset-options'),
  callSummary: $('call-summary'),
  transcript: $('transcript'),
  transcriptLines: $('transcript-lines'),
  status: $('status'),
  error: $('error'),
};

const END_MESSAGES = {
  left: 'You left the dinner.',
  user_stream_left: 'Your stream left the Vonage session, so the agent stopped.',
  max_duration: 'The dinner reached its maximum length.',
  idle_timeout: 'He said goodnight after a long silence.',
  ready_timeout: 'The dinner ended because the agent and browser never connected.',
  server_shutdown: 'The server shut down.',
  agent_exited: 'AI da Vinci left the dinner.',
  error: 'AI da Vinci stopped because of an error.',
};

let call = null; // the conversation in progress, if any

// --- Waiting room ------------------------------------------------------------------

const STORAGE_KEY = 'dinner-with-da-vinci-options';
const PAUSE_LABELS = { quick: 'Quick', relaxed: 'Relaxed', patient: 'Patient' };
const LANGUAGE_LABELS = { en: 'English, with an Italian accent', it: 'Italiano' };
const room = { catalog: null, persona: null, keyterms: [] };

// The disclosure and portrait credit, as the server's app/persona.py defines them.
async function loadPersona() {
  try {
    room.persona = await api('/api/persona');
  } catch {
    return; // Start still works; the agent's spoken greeting carries the disclosure.
  }
  const { portrait, displayName } = room.persona;
  for (const img of [ui.setupPortrait, ui.callPortrait]) img.src = portrait.path;
  for (const credit of [ui.setupCredit, ui.callCredit]) {
    const link = Object.assign(document.createElement('a'), {
      href: portrait.sourceUrl,
      textContent: portrait.credit,
      target: '_blank',
      rel: 'noopener',
    });
    credit.replaceChildren(link);
  }
  ui.agentName.textContent = displayName;
  renderDisclosure();
}

// The disclosure in the chosen language. In Italian, the English one stays too, because
// the rest of the page is in English.
function renderDisclosure() {
  const texts = room.persona?.languages;
  if (!texts) return;
  const language = selectedLanguage();
  ui.disclosure.replaceChildren(document.createTextNode(texts.en.disclosure));
  if (language !== 'en' && texts[language]) {
    const translated = Object.assign(document.createElement('span'), {
      lang: language,
      className: 'translated',
      textContent: texts[language].disclosure,
    });
    ui.disclosure.append(translated);
  }
  ui.callBanner.textContent = (texts[language] || texts.en).banner;
  ui.callBanner.lang = language;
}

function selectedLanguage() {
  return ui.language.querySelector('input:checked')?.value || 'en';
}

async function loadWaitingRoom() {
  let catalog;
  try {
    catalog = await api('/api/options');
  } catch (error) {
    // Not configured yet: Start shows the list of problems, as before.
    ui.stagesDetails.hidden = true;
    return;
  }
  room.catalog = catalog;
  if (catalog.agentMode === 'echo') {
    ui.stagesDetails.hidden = true;
    ui.language.closest('.field').hidden = true;
    ui.echoNote.hidden = false;
    return;
  }
  ui.language.replaceChildren(
    ...catalog.languages.map(({ code }) => radio('language', code, LANGUAGE_LABELS[code] || code)),
  );
  fillSelect(ui.model, catalog.openaiModels.map((m) => [m, m]));
  fillSelect(ui.voice, catalog.voices.map((v) => [v.id, v.name]));
  ui.pause.replaceChildren(
    ...Object.entries(catalog.limits.replyPauses).map(([value, secs]) =>
      radio('pause', value, PAUSE_LABELS[value] || value, `${secs}s`),
    ),
  );
  applyOptions({ ...catalog.defaults, ...savedOptions() });
}

function radio(name, value, text, note) {
  const label = document.createElement('label');
  const input = document.createElement('input');
  Object.assign(input, { type: 'radio', name, value });
  label.append(input, ` ${text} `);
  if (note) {
    const small = document.createElement('small');
    small.textContent = note;
    label.append(small);
  }
  return label;
}

function fillSelect(select, entries) {
  select.replaceChildren(
    ...entries.map(([value, text]) => Object.assign(document.createElement('option'), { value, text })),
  );
}

function applyOptions(o) {
  const language =
    ui.language.querySelector(`input[value="${o.language}"]`) || ui.language.querySelector('input');
  if (language) language.checked = true;
  room.keyterms = [...(o.keyterms || [])];
  renderKeyterms();
  ui.model.value = o.openaiModel;
  if (!ui.model.value) ui.model.selectedIndex = 0;
  ui.voice.value = o.voiceId;
  if (!ui.voice.value) ui.voice.selectedIndex = 0;
  ui.speed.value = o.voiceSpeed;
  ui.words.value = o.interruptMinWords;
  const pause = ui.pause.querySelector(`input[value="${o.replyPause}"]`) || ui.pause.querySelector('input');
  if (pause) pause.checked = true;
  renderOptionLabels();
  renderDisclosure();
}

function currentOptions() {
  return {
    language: selectedLanguage(),
    keyterms: room.keyterms,
    openaiModel: ui.model.value,
    voiceId: ui.voice.value,
    voiceSpeed: Number(ui.speed.value),
    interruptMinWords: Number(ui.words.value),
    replyPause: ui.pause.querySelector('input:checked')?.value || 'quick',
  };
}

function renderOptionLabels() {
  ui.speedValue.textContent = `${Number(ui.speed.value).toFixed(2).replace(/0$/, '')}×`;
  ui.wordsValue.textContent = ui.words.value;
}

function renderKeyterms() {
  for (const tag of ui.keytermTags.querySelectorAll('.tag')) tag.remove();
  for (const term of room.keyterms) {
    const tag = document.createElement('span');
    tag.className = 'tag';
    tag.textContent = term;
    const remove = Object.assign(document.createElement('button'), {
      type: 'button',
      textContent: '×',
      title: `Remove ${term}`,
    });
    remove.setAttribute('aria-label', `Remove ${term}`);
    remove.addEventListener('click', () => {
      room.keyterms = room.keyterms.filter((t) => t !== term);
      renderKeyterms();
      saveOptions();
    });
    tag.append(remove);
    ui.keytermTags.insertBefore(tag, ui.keytermInput);
  }
}

function addKeyterm() {
  const max = room.catalog?.limits.maxKeyterms || 20;
  const words = ui.keytermInput.value.split(',').map((w) => w.trim()).filter(Boolean);
  for (const word of words) {
    if (!room.keyterms.includes(word) && room.keyterms.length < max) room.keyterms.push(word);
  }
  ui.keytermInput.value = '';
  renderKeyterms();
  saveOptions();
}

function savedOptions() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function saveOptions() {
  if (!room.catalog || room.catalog.agentMode === 'echo') return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(currentOptions()));
  } catch {}
}

// The settings this call actually uses (as the server accepted them), shown in the room.
function renderCallSummary(options) {
  ui.callSummary.replaceChildren();
  if (!options || call?.agentMode === 'echo') return;
  const language = room.catalog?.languages.find((l) => l.code === options.language)?.name || options.language;
  const voice = [...ui.voice.options].find((o) => o.value === options.voiceId)?.text || options.voiceId;
  const terms = options.keyterms.length ? `, ${options.keyterms.length} keyterm${options.keyterms.length > 1 ? 's' : ''}` : '';
  const items = [
    ['listen', 'Deepgram', `${language}${terms}`],
    ['think', 'OpenAI', `${options.openaiModel}, in character`],
    ['speak', 'ElevenLabs', `${voice}, ${options.voiceSpeed}×`],
    ['turns', 'Turn-taking', `${PAUSE_LABELS[options.replyPause]} pause, ${options.interruptMinWords} words to interrupt`],
  ];
  for (const [kind, name, value] of items) {
    const item = document.createElement('li');
    item.className = kind;
    const label = document.createElement('strong');
    label.textContent = name;
    item.append(label, ` ${value}`);
    ui.callSummary.append(item);
  }
}

for (const el of [ui.model, ui.voice, ui.speed, ui.words]) {
  el.addEventListener('input', () => {
    renderOptionLabels();
    saveOptions();
  });
}
ui.pause.addEventListener('change', saveOptions);
ui.language.addEventListener('change', () => {
  renderDisclosure();
  saveOptions();
});
ui.keytermInput.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault();
    addKeyterm();
  } else if (event.key === 'Backspace' && !ui.keytermInput.value && room.keyterms.length) {
    room.keyterms.pop();
    renderKeyterms();
    saveOptions();
  }
});
ui.keytermInput.addEventListener('blur', () => ui.keytermInput.value.trim() && addKeyterm());
ui.keytermTags.addEventListener('click', (event) => {
  if (event.target === ui.keytermTags) ui.keytermInput.focus();
});
ui.resetOptions.addEventListener('click', () => {
  localStorage.removeItem(STORAGE_KEY);
  if (room.catalog) applyOptions(room.catalog.defaults);
});

// --- Small helpers ---------------------------------------------------------------

function setStatus(text) {
  ui.status.textContent = text;
  console.info('[demo]', text);
}

function showError(message, problems = []) {
  ui.error.replaceChildren(document.createTextNode(message));
  if (problems.length) {
    const list = document.createElement('ul');
    for (const problem of problems) {
      const item = document.createElement('li');
      item.textContent = problem;
      list.append(item);
    }
    ui.error.append(list);
  }
  ui.error.hidden = false;
}

function clearError() {
  ui.error.hidden = true;
  ui.error.replaceChildren();
}

class ApiError extends Error {
  constructor(status, message, problems = []) {
    super(message);
    this.status = status;
    this.problems = problems;
  }
}

async function api(path, { method = 'GET', key, body, keepalive = false } = {}) {
  const headers = {};
  if (key) headers.Authorization = `Bearer ${key}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      keepalive,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Can't reach the demo server. Is `docker compose up` still running?");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    const message =
      typeof detail === 'string' ? detail : detail?.message || `Request failed (HTTP ${response.status})`;
    throw new ApiError(response.status, message, detail?.problems || []);
  }
  return data;
}

// Our server puts {"role": "user"} or {"role": "agent"} in each token's connection data.
function roleOf(connection) {
  try {
    return JSON.parse(connection.data || '{}').role ?? null;
  } catch {
    return null;
  }
}

// Turns the SDK's raw audio levels into a meter value and a "speaking" flag.
function levelTracker(meter) {
  let average = 0;
  let lastLoud = 0;
  return {
    update(level) {
      average = level > average ? level : 0.7 * average + 0.3 * level;
      const scaled = Math.min(1, Math.max(0, Math.log10(average) / 1.5 + 1));
      meter.value = scaled;
      if (scaled > 0.35) lastLoud = performance.now();
    },
    get speaking() {
      return performance.now() - lastLoud < 500;
    },
    reset() {
      average = 0;
      lastLoud = 0;
      meter.value = 0;
    },
  };
}

const youLevel = levelTracker(ui.youLevel);
const agentLevel = levelTracker(ui.agentLevel);

function preflightProblem() {
  if (!window.isSecureContext) {
    return 'Browsers only allow microphone access on secure pages. Open http://localhost:8000 on this computer, or serve the app over HTTPS.';
  }
  if (typeof OT === 'undefined') {
    return "The Vonage Video Web SDK didn't load from unpkg.com. Check your network or content blocker, then reload.";
  }
  if (OT.checkSystemRequirements() !== 1) {
    return "This browser isn't supported by the Vonage Video Web SDK. Try a current Chrome, Edge, Firefox, or Safari.";
  }
  return null;
}

function mediaErrorMessage(error) {
  switch (error.name) {
    case 'OT_USER_MEDIA_ACCESS_DENIED':
      return 'Microphone access is blocked. Allow it in your browser\'s site settings (the icon in the address bar), then try again.';
    case 'OT_NO_DEVICES_FOUND':
    case 'OT_NO_VALID_CONSTRAINTS':
      return 'No microphone was found. Connect one and try again.';
    case 'OT_HARDWARE_UNAVAILABLE':
      return 'Your microphone or camera is being used by another app. Close it and try again.';
    default:
      return `Could not start your microphone: ${error.message}`;
  }
}

// --- Call flow -------------------------------------------------------------------

function createPublisher(useCamera) {
  return new Promise((resolve, reject) => {
    const publisher = OT.initPublisher(
      ui.publisher,
      {
        insertMode: 'append',
        width: '100%',
        height: '100%',
        name: 'You',
        videoSource: useCamera ? undefined : null, // null = audio only
        publishVideo: useCamera,
        style: {
          buttonDisplayMode: 'off',
          nameDisplayMode: 'off',
          audioLevelDisplayMode: 'off',
          archiveStatusDisplayMode: 'off',
        },
      },
      (error) => (error ? reject(new Error(mediaErrorMessage(error))) : resolve(publisher)),
    );
    publisher.on('accessDialogOpened', () =>
      setStatus('Allow microphone access in your browser\'s prompt…'),
    );
    publisher.on('audioLevelUpdated', (event) => youLevel.update(event.audioLevel));
    publisher.on('mediaStopped', () => {
      if (call && !call.ending) endCall('Your microphone stopped (was it unplugged?).', true);
    });
  });
}

function joinSession({ applicationId, vonageSessionId, token }) {
  const session = OT.initSession(applicationId, vonageSessionId);
  call.session = session;
  session.on({
    streamCreated: (event) => onStreamCreated(event.stream),
    streamDestroyed: (event) => {
      if (roleOf(event.stream.connection) === 'agent' && call && !call.ending) {
        setStatus('AI da Vinci left the dinner.');
      }
    },
    'signal:transcript': onTranscript,
    'signal:latency': onLatency,
    sessionReconnecting: () => setStatus('Network hiccup: reconnecting to Vonage Video…'),
    sessionReconnected: () => setStatus('Reconnected.'),
    sessionDisconnected: (event) => {
      if (call && !call.ending) {
        endCall(`Disconnected from Vonage Video (${event.reason}).`, event.reason !== 'clientDisconnected');
      }
    },
  });

  setStatus('Connecting to Vonage Video…');
  return new Promise((resolve, reject) => {
    session.connect(token, (connectError) => {
      if (connectError) {
        reject(new Error(`Could not connect to Vonage Video: ${connectError.message}`));
        return;
      }
      if (!call.agentSubscriber) setStatus('Connected. Waiting for AI da Vinci to take his seat…');
      session.publish(call.publisher, (publishError) =>
        publishError
          ? reject(new Error(`Could not publish your microphone: ${publishError.message}`))
          : resolve(),
      );
    });
  });
}

// The server sends one signal per turn. Only accept signals from the server
// (event.from is null), not ones another participant could send.
function onTranscript(event) {
  if (event.from) return;
  let line;
  try {
    line = JSON.parse(event.data);
  } catch {
    return;
  }
  if (typeof line?.text !== 'string') return;
  // Fixed lines (the greeting and farewell) are spoken a sentence at a time, so they
  // arrive in pieces. Back-to-back pieces from him belong in one bubble.
  const last = ui.transcriptLines.lastElementChild;
  if (line.role === 'agent' && last?.classList.contains('said') && !last.dataset.interrupted) {
    last.querySelector('span').textContent += ` ${line.text}`;
    if (line.interrupted) markInterrupted(last);
    return;
  }
  const item = document.createElement('li');
  item.className = line.role === 'user' ? 'heard' : 'said';
  const label = document.createElement('strong');
  label.textContent = line.role === 'user' ? 'Deepgram heard' : 'AI da Vinci said';
  const text = document.createElement('span');
  text.textContent = line.text;
  item.append(label, text);
  if (line.interrupted) markInterrupted(item);
  ui.transcriptLines.append(item);
  ui.transcript.hidden = false;
  item.scrollIntoView({ block: 'nearest' });
  // Your words reached the agent, and his reply hasn't started: he's thinking.
  if (call && line.role === 'user') call.thinking = true;
  if (call && line.role === 'agent') call.heardAgent = true;
}

function markInterrupted(item) {
  item.dataset.interrupted = 'true';
  const note = document.createElement('em');
  note.textContent = ' (interrupted: only the words you heard)';
  item.append(note);
}

// One per reply, sent when the agent starts speaking: how long you waited and where
// the time went. Same rule as transcripts: only from the server.
function onLatency(event) {
  if (event.from) return;
  let timing;
  try {
    timing = JSON.parse(event.data);
  } catch {
    return;
  }
  if (!Array.isArray(timing?.stages) || typeof timing.total !== 'number') return;
  const item = document.createElement('li');
  item.className = 'timing';
  const total = document.createElement('strong');
  total.textContent = `Replied after ${timing.total.toFixed(2)} s`;
  const bar = document.createElement('span');
  bar.className = 'bar';
  bar.setAttribute('aria-hidden', 'true');
  const parts = document.createElement('span');
  parts.className = 'parts';
  for (const { stage, secs } of timing.stages) {
    const kind = stage.toLowerCase().replace(/[^a-z]/g, '');
    const segment = document.createElement('span');
    segment.className = `seg ${kind}`;
    segment.style.flexGrow = String(Math.max(secs, 0.001));
    bar.append(segment);
    const part = document.createElement('span');
    part.className = `part ${kind}`;
    part.textContent = `${stage} ${secs.toFixed(2)}`;
    parts.append(part);
  }
  item.append(total, bar, parts);
  ui.transcriptLines.append(item);
  ui.transcript.hidden = false;
  item.scrollIntoView({ block: 'nearest' });
}

function onStreamCreated(stream) {
  const role = roleOf(stream.connection);
  if (role !== 'agent') {
    console.info(`[demo] Ignoring a stream from a "${role}" participant`);
    return;
  }
  if (!call || call.agentSubscriber) return;

  setStatus('AI da Vinci joined. Connecting to his audio…');
  const subscriber = call.session.subscribe(
    stream,
    ui.agentMedia,
    {
      insertMode: 'append',
      width: 1,
      height: 1,
      subscribeToVideo: false, // the agent publishes audio only
      style: {
        audioBlockedDisplayMode: 'off', // we show our own "enable audio" button
        buttonDisplayMode: 'off',
        nameDisplayMode: 'off',
        audioLevelDisplayMode: 'off',
        videoDisabledDisplayMode: 'off',
      },
    },
    (error) => {
      if (error) {
        endCall(`Could not subscribe to AI da Vinci: ${error.message}`, true);
      } else if (subscriber.isAudioBlocked()) {
        offerAudioUnblock();
      } else {
        signalReady();
      }
    },
  );
  call.agentSubscriber = subscriber;
  subscriber.on('audioBlocked', offerAudioUnblock);
  subscriber.on('audioUnblocked', () => {
    ui.enableAudio.hidden = true;
    signalReady();
  });
  subscriber.on('audioLevelUpdated', (event) => agentLevel.update(event.audioLevel));
}

function offerAudioUnblock() {
  ui.enableAudio.hidden = false;
  setStatus('Your browser blocked audio playback. Click "Enable audio" to hear him.');
}

// Tell the server the agent's audio can play here. The agent greets you only after this.
async function signalReady() {
  if (!call || call.ready || call.ending) return;
  call.ready = true;
  setStatus('Starting the conversation…');
  try {
    // Our connection ID lets the server send transcript signals to this page only.
    const connectionId = call.session.connection?.connectionId;
    await api(`/api/sessions/${call.id}/ready`, {
      method: 'POST',
      key: call.key,
      body: connectionId ? { connectionId } : undefined,
    });
    call.live = true;
    call.statusTimer = setInterval(renderLiveStatus, 250);
    renderLiveStatus();
  } catch (error) {
    endCall(error.message, true);
  }
}

// Status while talking, derived from the real audio levels of both streams and the
// transcript signals. It only says what is actually happening.
function renderLiveStatus() {
  if (!call?.live || call.ending) return;
  const speaking = agentLevel.speaking;
  ui.agentTile.classList.toggle('speaking', speaking);
  if (speaking) call.thinking = false;
  // The greeting is over once his first words have arrived and his audio has stopped.
  if (!speaking && call.heardAgent) call.greeted = true;
  if (call.agentMode === 'echo') {
    setStatusQuietly('Echo diagnostic: you should have heard a beep. Now speak and you will hear yourself.');
  } else if (speaking && !call.greeted) {
    // The greeting carries the disclosure, so the server doesn't let it be cut short.
    setStatusQuietly('AI da Vinci is greeting you.');
  } else if (speaking) {
    setStatusQuietly('AI da Vinci is speaking. Talk over him to interrupt.');
  } else if (call.muted) {
    setStatusQuietly("You're muted, so he can't hear you.");
  } else if (youLevel.speaking) {
    setStatusQuietly('Listening…');
  } else if (call.thinking) {
    setStatusQuietly('AI da Vinci is thinking…');
  } else {
    setStatusQuietly('Your turn: say something.');
  }
}

function setStatusQuietly(text) {
  if (ui.status.textContent !== text) ui.status.textContent = text;
}

function startPolling() {
  const current = call;
  current.poll = setInterval(async () => {
    if (current.ending) return;
    let status;
    try {
      status = await api(`/api/sessions/${current.id}`, { key: current.key });
    } catch (error) {
      if (current.ending) return;
      if (error.status === 404) {
        endCall('The server no longer knows this session (did it restart?).', true, { serverEnded: true });
      } else if (++current.pollFailures >= 3) {
        endCall('Lost contact with the demo server.', true, { serverEnded: true });
      }
      return;
    }
    if (current.ending) return; // the user left while this request was in flight
    current.pollFailures = 0;
    ui.agentHearing.hidden = !status.agent.hearingUser;
    current.deadline = Date.now() + status.secondsRemaining * 1000;
    if (status.state === 'ended' || status.state === 'failed') {
      const message = END_MESSAGES[status.endReason] || 'The session ended.';
      const detail = status.error ? ` ${status.error}` : '';
      endCall(message + detail, status.state === 'failed', { serverEnded: true });
    }
  }, 2000);
}

function startCountdown() {
  const current = call;
  const tick = () => {
    const seconds = Math.max(0, Math.round((current.deadline - Date.now()) / 1000));
    ui.timeLeft.textContent = `Time left ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  };
  tick();
  current.countdown = setInterval(tick, 1000);
}

function showCallUi() {
  ui.setup.hidden = true;
  ui.call.hidden = false;
  ui.publisher.hidden = !call.useCamera;
  ui.youPlaceholder.hidden = call.useCamera;
  ui.camera.hidden = !call.useCamera;
  ui.camera.textContent = 'Turn camera off';
  ui.mute.textContent = 'Mute';
  ui.mute.setAttribute('aria-pressed', 'false');
  ui.mutedBadge.hidden = true;
  ui.agentHearing.hidden = true;
}

async function start() {
  clearError();
  const problem = preflightProblem();
  if (problem) {
    showError(problem);
    return;
  }
  ui.start.disabled = true;
  call = {
    useCamera: ui.useCamera.checked,
    muted: false,
    ready: false,
    live: false,
    thinking: false,
    greeted: false,
    heardAgent: false,
    ending: false,
    pollFailures: 0,
  };
  youLevel.reset();
  agentLevel.reset();
  ui.transcriptLines.replaceChildren();
  ui.transcript.hidden = true;

  try {
    setStatus('Asking for microphone access…');
    call.publisher = await createPublisher(call.useCamera);

    setStatus('Starting a session…');
    const options = room.catalog && room.catalog.agentMode !== 'echo' ? currentOptions() : undefined;
    const created = await api('/api/sessions', { method: 'POST', body: options ? { options } : {} });
    Object.assign(call, { id: created.id, key: created.sessionKey, agentMode: created.agentMode });
    call.deadline = Date.now() + created.maxSessionSeconds * 1000;

    showCallUi();
    renderCallSummary(created.options);
    startPolling();
    startCountdown();
    await joinSession(created);
  } catch (error) {
    await endCall(error.message, true, { problems: error.problems || [] });
  }
}

async function endCall(message, isError = false, { serverEnded = false, problems = [] } = {}) {
  if (!call || call.ending) return;
  const ending = call;
  ending.ending = true;
  clearInterval(ending.poll);
  clearInterval(ending.countdown);
  clearInterval(ending.statusTimer);

  // Leave the Vonage session right away; stopping the agent can take a few seconds.
  try {
    ending.session?.disconnect();
  } catch {}
  try {
    ending.publisher?.destroy();
  } catch {}
  if (ending.id && !serverEnded) {
    setStatus('Ending the session…');
    try {
      await api(`/api/sessions/${ending.id}/end`, { method: 'POST', key: ending.key });
    } catch (error) {
      console.warn('[demo] Could not end the session cleanly:', error.message);
    }
  }

  call = null;
  ui.agentTile.classList.remove('speaking');
  ui.call.hidden = true;
  ui.setup.hidden = false;
  ui.start.disabled = false;
  ui.enableAudio.hidden = true;
  ui.timeLeft.textContent = '';
  setStatus(message);
  if (isError) showError(message, problems);
}

// --- Controls --------------------------------------------------------------------

ui.start.addEventListener('click', start);

ui.leave.addEventListener('click', () => endCall('You left the conversation.'));

ui.mute.addEventListener('click', () => {
  if (!call?.publisher) return;
  call.muted = !call.muted;
  call.publisher.publishAudio(!call.muted);
  ui.mute.textContent = call.muted ? 'Unmute' : 'Mute';
  ui.mute.setAttribute('aria-pressed', String(call.muted));
  ui.mutedBadge.hidden = !call.muted;
  renderLiveStatus();
});

ui.camera.addEventListener('click', () => {
  if (!call?.publisher) return;
  const on = ui.camera.textContent === 'Turn camera on';
  call.publisher.publishVideo(on);
  ui.camera.textContent = on ? 'Turn camera off' : 'Turn camera on';
});

ui.enableAudio.addEventListener('click', async () => {
  try {
    await OT.unblockAudio(); // must run inside a click handler
  } catch (error) {
    showError(`Could not enable audio: ${error.message}`);
  }
});

// Best effort: stop the agent if the tab closes. No navigation, no prompts.
window.addEventListener('pagehide', () => {
  if (call?.id && !call.ending) {
    api(`/api/sessions/${call.id}/end`, { method: 'POST', key: call.key, keepalive: true }).catch(
      () => {},
    );
  }
});

loadPersona();
loadWaitingRoom();
