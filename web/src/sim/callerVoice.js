// Ringback tone (what the caller hears: normal ringing, nothing else).
//
// There is no simulated caller voice anymore — both sides of the conversation
// are recorded live through the browser mic. The recap whisper is always real
// Rime audio fetched from the backend.

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