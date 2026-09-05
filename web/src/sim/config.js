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

// ── Spoken language (fixed — no EN/HI UI switch) ─────────────────────────────
// The website copy is always English; the *voice* layer is Hinglish:
//   - the mic transcribes Hindi with the Nova-3 Hindi model (`hi` — Deepgram's
//     `multi` mode is notorious for misdetecting Hindi as Spanish). The
//     backend romanizes the Devanagari into Latin-script Hinglish, so "hello
//     भाई कैसे हो" arrives as "hello bhai kaise ho".
//   - the recap is built/spoken in Hinglish (`hi` selects the Hinglish frames
//     on the backend and Rime's Hindi-accented voice `nadi`)
export const STT_LANG = 'hi' // Hindi STT → romanized to Hinglish on the backend
export const RECAP_LANG = 'hi' // Hinglish spoken recap

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

// Scripted caller ("mock Z") lines for the India auto-pickup option. The text
// is authored (not transcribed), so it is recorded straight to thread memory
// as CALLER turns — it never has to be "taken as input" from the mic. gapMs
// is silence after each line so the presenter can reply.
//
// Z speaks HINGLISH too (Latin script) so the whole India demo — recap,
// caller, and your voice input — is one Hinglish experience. Z's voice is
// `taru`, Rime's native Hindi male voice on coda (lang hi); the recap whisper
// on the private track stays `nadi` (female Hindi).
export const MOCK_CALLER = {
  speaker: 'taru', // male native Hindi Rime voice (coda) — distinct from the recap whisper 'nadi'
  language: RECAP_LANG, // 'hi' — Hinglish script, spoken with the Hindi voice
  model: null, // inherit the backend default (coda)
  timeScaleFactor: 1.0, // natural pace, not the sped-up recap cadence
  duckedVolume: 0.3, // while the recap whisper is still playing
  fullVolume: 0.85, // once live (recap finished / interrupted)
  lines: [
    { text: 'Hey — hello? Sun paa rahe ho? Network ne finally call connect kar di.', gapMs: 2600 },
    { text: 'To, kya aapko finance se volume discount ke baare mein poochhne ka mauka mila?', gapMs: 3200 },
    { text: 'Aur kya hum Q3 numbers par ab bhi agree hain?', gapMs: 2800 },
    { text: 'Theek hai, meri taraf se sab clear. Sorting out karne ke liye thanks.', gapMs: 0 },
  ],
}

// ── Barge-in phrase examples (demo script §03) ──────────────────────────────
// The detector is NOT anchored to one canonical sentence: any English, Hinglish
// or Hindi phrasing that carries a pickup verb auto-answers ("call utha lo",
// "mujhe pta hai call utha lo", "pick up the phone"…), and stop phrases halt
// the recap while the phone keeps ringing. The demo chips below exercise the
// same intent through different wordings; Devanagari Hindi works too.
export const BARGE_EXAMPLES = {
  answer: [
    'call utha lo',
    'I know, just pick up the call',
    'mujhe pta hai, call utha lo',
  ],
  stop: [
    'Hold on, one second',
    'skip karo',
    'mujhe pata hai',
  ],
}

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