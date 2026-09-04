// Simulated caller voice (Z) + ringback tone.
//
// IMPORTANT (AGENTS.md Rule 2): this browser voice is used ONLY for the
// scripted demo caller on the "caller" side. It is visibly labelled
// "simulated caller". The recap whisper — the judged spoken output — is always
// real Rime audio fetched from the backend; it never touches speechSynthesis.

const SUPPORTED_HINTS = [
  /en[-_](US|GB|CA|AU)/i,
  /en/i,
]

function pickVoice() {
  const voices = window.speechSynthesis ? window.speechSynthesis.getVoices() : []
  if (!voices.length) return null
  const english = voices.filter((v) => SUPPORTED_HINTS[0].test(v.lang))
  const anyEnglish = voices.filter((v) => SUPPORTED_HINTS[1].test(v.lang))
  const pool = english.length ? english : anyEnglish.length ? anyEnglish : voices
  // Prefer a slightly deeper, "male"-ish natural voice when available.
  const natural = pool.find((v) => /natural|neural/i.test(v.name)) || pool[0]
  return natural
}

let cachedVoice = null

export function ensureVoicesLoaded() {
  if (!('speechSynthesis' in window)) return
  // Voices may load asynchronously; re-query when the queue changes.
  if (!cachedVoice) cachedVoice = pickVoice()
  window.speechSynthesis.onvoiceschanged = () => {
    cachedVoice = pickVoice()
  }
}

export function callerVoiceSupported() {
  return 'speechSynthesis' in window
}

/**
 * Speak one simulated caller line. Resolves when the line is finished
 * (or immediately cancelled by stopCallerSpeech()).
 */
export function speakCallerLine(text, { onBoundary } = {}) {
  return new Promise((resolve) => {
    if (!callerVoiceSupported()) {
      resolve()
      return
    }
    if (!cachedVoice) cachedVoice = pickVoice()
    const utterance = new SpeechSynthesisUtterance(text)
    if (cachedVoice) utterance.voice = cachedVoice
    utterance.rate = 1.02
    utterance.pitch = 0.92
    utterance.volume = 1
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      resolve()
    }
    if (onBoundary && typeof utterance.addEventListener === 'function') {
      utterance.addEventListener('boundary', onBoundary)
    }
    utterance.onend = finish
    utterance.onerror = finish
    window.speechSynthesis.speak(utterance)
  })
}

export function stopCallerSpeech() {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel()
  }
}

// ── Ringback tone (what the caller hears: normal ringing, nothing else) ──────
let ringCtx = null
let ringTimer = null
let ringGain = null

export function startRingback() {
  if (ringCtx) return
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    ringCtx = new Ctx()
    ringGain = ringCtx.createGain()
    ringGain.gain.value = 0.05
    ringGain.connect(ringCtx.destination)
    const pattern = () => {
      if (!ringCtx) return
      // US cadence: ~2s of tone bursts then ~4s silence
      for (let i = 0; i < 4; i += 1) {
        const osc = ringCtx.createOscillator()
        const gain = ringCtx.createGain()
        osc.type = 'sine'
        osc.frequency.value = 440
        const t0 = ringCtx.currentTime + i * 0.45
        gain.gain.setValueAtTime(0.0001, t0)
        gain.gain.exponentialRampToValueAtTime(1, t0 + 0.05)
        gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.4)
        osc.connect(gain)
        gain.connect(ringGain)
        osc.start(t0)
        osc.stop(t0 + 0.45)
      }
      ringTimer = setTimeout(pattern, 2200)
    }
    pattern()
  } catch {
    ringCtx = null // no audio context available — silent demo is fine
  }
}

export function stopRingback() {
  if (ringTimer) clearTimeout(ringTimer)
  ringTimer = null
  if (ringCtx) {
    ringCtx.close().catch(() => {})
    ringCtx = null
    ringGain = null
  }
}
