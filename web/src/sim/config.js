// Scenario + copy constants for the interactive Continuum demo simulation.
// The caller (Z) is a scripted demo avatar; "You" speaks live through the mic.

export const CALLER = {
  name: 'Z',
  number: '+1 (415) 555-0199',
  callerId: '+14155550199',
}

export const SESSIONS = {
  call1: 'sim-demo-call-1', // yesterday's interrupted call
  call2: 'sim-demo-call-2', // today's reconnect
}

export const PRIVATE_TRACK_ID = 'continuum-private-whisper'

// ── Call one (yesterday) — Z's scripted lines ───────────────────────────────
// The last line is intentionally cut short: that is the forced network drop.
export const CALL1_Z_LINES = [
  {
    text: 'Hey, it\'s Z — sorry to call back so soon. I wanted to follow up on the Q3 numbers before we talk to the vendor.',
    hint: 'Say hello, then confirm the unit price you quoted.',
  },
  {
    text: 'Great. So just to lock it in — the unit price we discussed was around four hundred dollars, right?',
    hint: 'Reply something like: "Right — four hundred dollars per unit, that\'s the number we quoted."',
  },
  {
    text: 'Perfect. And can you check with finance on volume discounts before we sign?',
    hint: 'Reply: "Absolutely, I\'ll check with finance today and get back to you."',
  },
  {
    text: 'Awesome. And one more thing — the ticket number is XYZ-4821, I just wanted to make sure you got it befo',
    cut: true, // connection drops mid-sentence here
    hint: '…and the line drops mid-sentence. No goodbye — that is the interruption.',
  },
]

// Suggested "You" replies shown as chips (also the deterministic fallback when
// the live mic / STT is unavailable). They double as memory-extraction anchors.
export const CALL1_USER_SUGGESTIONS = [
  'Hey Z — happy to. What do you need?',
  'Right — four hundred dollars per unit, that\'s the number we quoted.',
  'Absolutely, I\'ll check with finance today and get back to you.',
]

// ── Call two (today, after the recap / barge-in) ─────────────────────────────
export const CALL2_Z_LINES = [
  {
    text: 'Hey — sorry, we got cut off yesterday. Did you get a chance to check with finance?',
    hint: 'Answer naturally — you already know exactly where you left off.',
  },
  {
    text: 'Perfect, that\'s everything I needed. Talk soon!',
    hint: 'Wrap up the call when you\'re ready.',
  },
]

export const CALL2_USER_SUGGESTIONS = [
  'Yeah — finance confirmed we can do the volume discount. I\'ll send the numbers over.',
  'Great, talk soon!',
]

// ── Barge-in phrases (demo-script §03) ───────────────────────────────────────
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
}
