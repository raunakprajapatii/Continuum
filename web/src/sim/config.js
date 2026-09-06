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

// ── Spoken language (auto — follows the conversation) ────────────────────────
// The website copy is always English; the *voice* layer follows the language
// the call was actually spoken in:
//   - the mic transcribes with the Nova-3 Hindi model (`hi` — Deepgram's
//     `multi` mode is notorious for misdetecting Hindi as Spanish). The
//     backend romanizes the Devanagari into Latin-script Hinglish, so "hello
//     भाई कैसे हो" arrives as "hello bhai kaise ho".
//   - RECAP_LANG='auto': the backend inspects the stored thread and picks
//     `en` for English conversations (English frames, `eyre` voice) and `hi`
//     for Hindi / Hinglish conversations (Hinglish frames, `nadi` voice).
//   - the scripted caller (mock Z) speaks the same language as the recap.
export const STT_LANG = 'hi' // Hindi STT → romanized to Hinglish on the backend
export const RECAP_LANG = 'auto' // recap language follows the conversation

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
// The script IS the Meridian enterprise scenario: Z is the procurement
// manager for a textiles client confirming commodity quotes against the
// live enterprise catalog (mocks/enterprise) — Basmati rice 1121 ($940/t),
// Copper cathode ($8,940/t, LME-linked) and Shankar-6 cotton ($1,275/bale).
// The product names + $-prices are exactly what the Brain extractor keys as
// `price_<sku>` facts, so the freshness checker can re-verify them against
// the feed on port 8001.
//
// Z speaks the SAME language the recap resolved to (EN or HI) so the whole
// India demo — recap, caller, and your voice input — is one language.
// Voices on coda: 'taru' (male Hindi) for Hinglish, 'cupola' (male,
// professional American) for English — both distinct from the recap whisper
// ('nadi' / 'eyre').
export const MOCK_CALLER = {
  speakers: { en: 'cupola', hi: 'taru' }, // male caller voice per recap language
  language: RECAP_LANG, // resolved to the recap's actual language per run
  model: null, // inherit the backend default (coda)
  timeScaleFactor: 1.0, // natural pace, not the sped-up recap cadence
  duckedVolume: 0.3, // while the recap whisper is still playing
  fullVolume: 0.85, // once live (recap finished / interrupted)
  lines: {
    en: [
      { text: 'Hey — hello? Can you hear me? The network finally connected the call.', gapMs: 2600 },
      { text: 'So, did you get a chance to check the Basmati rice 1121 quote? Export grade is at $940 per tonne.', gapMs: 3200 },
      { text: 'And on the copper cathode — the LME settlement came through. Last quoted $8,940 per tonne.', gapMs: 2800 },
      { text: 'Great. And the Shankar 6 cotton bales — can we lock $1,275?', gapMs: 2600 },
      { text: 'Perfect. I will send the revised purchase order for the basmati by tomorrow morning.', gapMs: 0 },
    ],
    hi: [
      { text: 'Hey — hello? Sun paa rahe ho? Network ne finally call connect kar di.', gapMs: 2600 },
      { text: 'To, basmati rice 1121 ka quote check kiya? Export grade ab $940 per tonne hai.', gapMs: 3200 },
      { text: 'Aur copper cathode — LME settlement aa gaya. Last quote $8,940 per tonne tha.', gapMs: 2800 },
      { text: 'Achha. Aur Shankar 6 cotton bales — $1,275 par lock kar sakte hain?', gapMs: 2600 },
      { text: 'Perfect. Kal subah basmati ka revised purchase order bhej dunga.', gapMs: 0 },
    ],
  },
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