// Scenario + copy constants for the interactive Continuum demo simulation.
// Both sides of the conversation are recorded LIVE through the browser mic
// (Deepgram STT) — there is no scripted caller and no mock voice.

export const CALLER = {
  name: 'Z',
  number: '+1 (415) 555-0199',
  callerId: '+14155550199',
}

export const SESSIONS = {
  call1: 'sim-demo-call-1', // first live conversation (interrupted)
  call2: 'sim-demo-call-2', // the reconnect conversation
}

export const PRIVATE_TRACK_ID = 'continuum-private-whisper'

// Who records through the shared browser mic. USER = User 1 (you), CALLER =
// User 2 (Z in the demo narrative). The labels map 1:1 onto the backend
// Speaker enum used by the Brain extractor.
export const SPEAKERS = {
  USER: { label: 'User 1', short: 'U1' },
  CALLER: { label: 'User 2', short: 'U2' },
}

// ── Network auto-pickup (India ring behaviour) ───────────────────────────────
// In India the phone rings ~30 s before the network connects the call by
// itself. If the recap whisper is still playing at that point it keeps playing;
// a scripted (mock) caller then joins at reduced volume so the recap stays
// intelligible. This is the test fixture for that overlap.
export const AUTO_PICKUP = {
  // Seconds of ringing before the network auto-connects the call.
  ringDelayS: 30,
}

// Scripted caller ("mock Z") lines for the auto-pickup option. The text is
// authored (not transcribed), so it is recorded straight to thread memory as
// CALLER turns — it never has to be "taken as input" from the mic. gapMs is
// silence after each line so the presenter can reply.
export const MOCK_CALLER = {
  speaker: 'masonry', // distinct male Rime voice — the recap whisper stays 'eyre'
  model: null, // inherit the backend default (coda)
  timeScaleFactor: 1.0, // natural pace, not the sped-up recap cadence
  duckedVolume: 0.3, // while the recap whisper is still playing
  fullVolume: 0.85, // once live (recap finished / interrupted)
  lines: [
    { text: 'Hey — hello? Can you hear me? The network finally connected us.', gapMs: 2600 },
    { text: 'So, did you get a chance to check with finance on the volume discount?', gapMs: 3200 },
    { text: 'And are we still good on the Q3 numbers?', gapMs: 2800 },
    { text: 'Alright, that works for me. Thanks for sorting it out.', gapMs: 0 },
  ],
  // Hindi script used when the dashboard language is Hindi (India demo).
  linesHi: [
    { text: 'हे — हैलो? क्या आप मुझे सुन पा रहे हैं? नेटवर्क ने आखिरकार कॉल कनेक्ट कर दी।', gapMs: 2600 },
    { text: 'तो, क्या आपको फाइनेंस से वॉल्यूम डिस्काउंट के बारे में पूछने का मौका मिला?', gapMs: 3200 },
    { text: 'और क्या हम Q3 के आँकड़ों पर अभी भी सहमत हैं?', gapMs: 2800 },
    { text: 'ठीक है, मेरे लिए यह काम कर गया। इसे सुलझाने के लिए धन्यवाद।', gapMs: 0 },
  ],
}

// ── Barge-in phrases (demo script §03) ───────────────────────────────────────
export const BARGE_ACTION_PHRASE = 'I know, just pick up the call'
export const BARGE_STOP_PHRASES = ['Hold on, one second', 'Skip — I remember']

export const INTENT_LABELS = {
  ANSWER_CALL: 'auto_answer',
  DISMISS_RECAP: 'stop_only',
  IGNORE: 'ignored',
}

// Wall-clock anchors for the on-screen log: call one happens "yesterday", the
// callback happens "next morning" — the jump is shown on screen (demo script §04).
export const CLOCK = {
  call1Start: { hour: 14, minute: 2, second: 0 },
  call2Start: { hour: 9, minute: 14, second: 0 }, // next day
}

export const EVENT_KINDS = {
  'call.disconnect_detected': 'call',
  'thread.marked_interrupted': 'memory',
  'call.inbound_ring': 'call',
  'thread.match_found': 'memory',
  'recap.generation_started': 'brain',
  'recap.text_ready': 'brain',
  'freshness.discrepancy_found': 'alert',
  'recap.tts_first_audio': 'voice',
  'barge_in.detected': 'action',
  'tts.playback_halted': 'action',
  'barge_in.intent_classified': 'action',
  'call.auto_answer_triggered': 'call',
  'call.connected': 'call',
  'call.completed': 'call',
  'turn.recorded': 'memory',
  'caller.mock_line': 'voice',
  'caller.echo_filtered': 'action',
}