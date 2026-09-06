import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { useSimulation, PHASE, RECAP_STATE } from './useSimulation.js'
import * as api from './api.js'
import * as callerVoice from './callerVoice.js'
import * as userMic from './userMic.js'
import { preloadMockLines } from './mockCaller.js'
import { CALLER, PRIVATE_TRACK_ID, SESSIONS } from './config.js'

// ── module mocks ─────────────────────────────────────────────────────────────
vi.mock('./api.js', () => ({
  getCapabilities: vi.fn(),
  resetDemo: vi.fn(),
  recordTurn: vi.fn(),
  endCallOne: vi.fn(),
  buildRecap: vi.fn(),
  classifyIntent: vi.fn(),
  fetchRimeAudio: vi.fn(),
}))

vi.mock('./callerVoice.js', () => ({
  startRingback: vi.fn(),
  stopRingback: vi.fn(),
}))

vi.mock('./userMic.js', () => ({
  micStreamSupported: vi.fn(() => true),
  startMicStream: vi.fn(),
}))

vi.mock('./mockCaller.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, preloadMockLines: vi.fn() }
})

// ── fixtures ─────────────────────────────────────────────────────────────────
const RECAP_PAYLOAD = () => ({
  text: 'Heads up — Basmati rice 1121 is now $955 per tonne. The copper cathode holds at $8,940. Ready to lock in the new rice quote?',
  language: 'en',
  speaker: 'eyre',
  model: 'coda',
  time_scale_factor: 1.25,
  freshness: {
    results: [
      { key: 'price_basmati-1121', status: 'CHANGED', label: 'Basmati rice 1121', cached_value: '$940', live_value: '$955', latency_ms: 41 },
    ],
  },
  metrics: {},
})

const MOCK_LINES = [
  { index: 0, text: 'Hey — hello? Can you hear me? The network finally connected the call.', gapMs: 2600, objectUrl: 'blob:mock-0' },
  { index: 1, text: 'So, did you get a chance to check the Basmati rice 1121 quote?', gapMs: 3200, objectUrl: 'blob:mock-1' },
]

// ── minimal hook harness (no testing-library dependency) ─────────────────────
const micHandles = []
let harnesses = []

async function renderHook(useHook) {
  let latest
  let root
  const container = document.createElement('div')
  document.body.appendChild(container)
  function Harness() {
    latest = useHook()
    return null
  }
  root = createRoot(container)
  await act(async () => {
    root.render(<Harness />)
  })
  const harness = {
    get result() {
      return latest
    },
    async actAsync(fn) {
      await act(async () => {
        await fn()
      })
    },
    unmount() {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
  harnesses.push(harness)
  return harness
}

beforeEach(() => {
  vi.clearAllMocks()
  micHandles.length = 0
  window.__audioInstances.length = 0
  window.__audioPlayShouldFail = false
  api.getCapabilities.mockResolvedValue({ ready: true, stt: { enabled: false } })
  api.resetDemo.mockResolvedValue(undefined)
  api.recordTurn.mockResolvedValue(undefined)
  api.endCallOne.mockResolvedValue({ thread_id: 'z-contact-01', is_interrupted: true })
  api.buildRecap.mockResolvedValue(RECAP_PAYLOAD())
  api.classifyIntent.mockResolvedValue({ intent: 'IGNORE' })
  api.fetchRimeAudio.mockResolvedValue({ objectUrl: 'blob:recap', track: 'continuum-private-whisper', fetchMs: 12 })
  preloadMockLines.mockResolvedValue([])
  userMic.startMicStream.mockImplementation(async ({ onReady, onTranscript, onError }) => {
    const handle = {
      stop: vi.fn(),
      ready: () => onReady && onReady(),
      emitInterim: (text) => onTranscript({ text, isFinal: false }),
      emitFinal: (text) => onTranscript({ text, isFinal: true }),
      emitError: (message) => onError({ code: 'stt', message }),
    }
    micHandles.push(handle)
    return handle
  })
})

afterEach(() => {
  while (harnesses.length) harnesses.pop().unmount()
  vi.useRealTimers()
  window.__audioPlayShouldFail = false
})

// ── bootstrap ────────────────────────────────────────────────────────────────
describe('bootstrap', () => {
  it('loads capabilities on mount and reports ready', async () => {
    const h = await renderHook(useSimulation)
    expect(h.result.capsState).toBe('ready')
    expect(h.result.caps).toEqual({ ready: true, stt: { enabled: false } })
    expect(api.getCapabilities).toHaveBeenCalledTimes(1)
  })

  it('falls back to idle with an error when the backend is unreachable', async () => {
    api.getCapabilities.mockRejectedValue(new Error('ECONNREFUSED'))
    const h = await renderHook(useSimulation)
    expect(h.result.capsState).toBe('error')
    expect(h.result.capsError).toContain('ECONNREFUSED')
    expect(h.result.phase).toBe(PHASE.IDLE)
  })

  it('retryCaps re-probes the backend', async () => {
    api.getCapabilities.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce({ ready: true, stt: { enabled: true } })
    const h = await renderHook(useSimulation)
    expect(h.result.capsState).toBe('error')
    await h.actAsync(() => h.result.retryCaps())
    expect(h.result.capsState).toBe('ready')
    expect(h.result.caps.stt.enabled).toBe(true)
  })
})

// ── call one (yesterday) ─────────────────────────────────────────────────────
describe('call one', () => {
  it('startCall1 resets the demo, starts the clock and opens the call', async () => {
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.startCall1())
    expect(h.result.phase).toBe(PHASE.CALL1)
    expect(h.result.callStateLabel).toBe('CONNECTED')
    expect(api.resetDemo).toHaveBeenCalledWith({
      callerId: CALLER.callerId,
      sessionIds: [SESSIONS.call1, SESSIONS.call2],
    })
    expect(h.result.events.some((e) => e.name === 'call.connected')).toBe(true)
    // STT gating is surfaced to the presenter when the backend has no Deepgram key.
    expect(h.result.micError).toContain('Deepgram STT unavailable')
  })

  it('simulateDrop marks the thread interrupted and persists memory', async () => {
    api.endCallOne.mockResolvedValue({ thread_id: 'z-contact-01', is_interrupted: true, turn_count: 3 })
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.startCall1())
    await h.actAsync(() => h.result.simulateDrop())
    expect(h.result.phase).toBe(PHASE.MEMORY)
    expect(h.result.memoryBusy).toBe(false)
    expect(h.result.threadSummary).toEqual({ thread_id: 'z-contact-01', is_interrupted: true, turn_count: 3 })
    expect(api.endCallOne).toHaveBeenCalledWith({
      sessionId: SESSIONS.call1,
      callerId: CALLER.callerId,
      callerName: CALLER.name,
      interrupted: true,
    })
    expect(h.result.events.some((e) => e.name === 'call.disconnect_detected')).toBe(true)
    expect(h.result.events.some((e) => e.name === 'thread.marked_interrupted')).toBe(true)
  })

  it('startTurn without STT support reports a mic error and returns null', async () => {
    const h = await renderHook(useSimulation)
    let handle
    await h.actAsync(async () => {
      handle = await h.result.startTurn('USER', SESSIONS.call1)
    })
    expect(handle).toBeNull()
    expect(h.result.micError).toContain('Live mic needs the backend')
  })

  it('startTurn + endTurn commit the accumulated transcript as one turn', async () => {
    api.getCapabilities.mockResolvedValue({ ready: true, stt: { enabled: true } })
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.startCall1())
    let handle
    await h.actAsync(async () => {
      handle = await h.result.startTurn('USER', SESSIONS.call1)
    })
    expect(handle).toBeTruthy()
    const mic = micHandles.at(-1)
    await h.actAsync(() => {
      mic.emitInterim('hello bhai')
      mic.emitFinal('hello bhai kaise ho')
      mic.emitFinal('basmati ka quote kya hai')
    })
    expect(h.result.interimText).toBe('')
    await h.actAsync(() => h.result.endTurn())
    expect(h.result.call1Turns).toHaveLength(1)
    expect(h.result.call1Turns[0]).toMatchObject({
      speaker: 'USER',
      text: 'hello bhai kaise ho basmati ka quote kya hai',
      live: false,
      mock: false,
    })
    expect(api.recordTurn).toHaveBeenCalledWith({
      sessionId: SESSIONS.call1,
      speaker: 'USER',
      text: 'hello bhai kaise ho basmati ka quote kya hai',
    })
    expect(h.result.events.some((e) => e.name === 'turn.recorded')).toBe(true)
  })
})

// ── callback recap ───────────────────────────────────────────────────────────
describe('callback recap', () => {
  it('continueToCallback builds the recap and surfaces freshness changes', async () => {
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    expect(h.result.phase).toBe(PHASE.RECAP)
    expect(h.result.recapState).toBe(RECAP_STATE.READY)
    expect(h.result.recap.text).toBe(RECAP_PAYLOAD().text)
    expect(h.result.recap.sentences.length).toBe(3)
    expect(api.buildRecap).toHaveBeenCalledWith({
      callerId: CALLER.callerId,
      sessionId: SESSIONS.call2,
      ringWindowS: 30,
      language: 'auto',
    })
    const freshness = h.result.events.filter((e) => e.name === 'freshness.discrepancy_found')
    expect(freshness).toHaveLength(1)
    expect(freshness[0].meta).toMatchObject({ key: 'price_basmati-1121', cached: '$940', live: '$955' })
    expect(h.result.events.some((e) => e.name === 'recap.text_ready')).toBe(true)
    expect(callerVoice.startRingback).toHaveBeenCalled()
  })

  it('reports an error when recap generation fails', async () => {
    api.buildRecap.mockRejectedValue(new Error('enterprise feed down'))
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    expect(h.result.recapState).toBe(RECAP_STATE.ERROR)
    expect(h.result.error).toContain('enterprise feed down')
  })

  it('plays the recap audio on the private track and completes when it ends', async () => {
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('full'))
    expect(h.result.recapState).toBe(RECAP_STATE.PLAYING)
    expect(h.result.audioStatus).toBe('playing')
    expect(api.fetchRimeAudio).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ trackId: PRIVATE_TRACK_ID, lang: 'en' }))
    expect(h.result.events.some((e) => e.name === 'recap.tts_first_audio')).toBe(true)

    const audio = window.__audioInstances.at(-1)
    expect(audio).toBeTruthy()
    expect(audio.paused).toBe(false)
    // Caption progress tracks playback position.
    audio.duration = 10
    audio.currentTime = 9.9
    await h.actAsync(() => {
      audio.ontimeupdate()
    })
    expect(h.result.spokenIdx).toBeGreaterThan(0)
    await h.actAsync(() => {
      audio.onended()
    })
    expect(h.result.recapState).toBe(RECAP_STATE.DONE)
    expect(h.result.spokenIdx).toBe(h.result.recap.sentences.length - 1)
  })

  it('enters NEEDS_GESTURE when autoplay is blocked, then resumes on a gesture', async () => {
    window.__audioPlayShouldFail = true
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('full'))
    expect(h.result.recapState).toBe(RECAP_STATE.NEEDS_GESTURE)
    expect(h.result.audioStatus).toBe('blocked')
    // A fresh gesture retries the same warm audio element.
    window.__audioPlayShouldFail = false
    await h.actAsync(() => h.result.resumeRecapPlayback())
    expect(h.result.recapState).toBe(RECAP_STATE.PLAYING)
  })
})

// ── barge-in ─────────────────────────────────────────────────────────────────
describe('barge-in', () => {
  it('halts playback and auto-answers on an ANSWER_CALL phrase', async () => {
    api.classifyIntent.mockResolvedValue({ intent: 'ANSWER_CALL' })
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('full'))
    expect(h.result.recapState).toBe(RECAP_STATE.PLAYING)

    await h.actAsync(() => h.result.testPhrase('call utha lo'))
    expect(h.result.phase).toBe(PHASE.CONNECTED)
    expect(h.result.recapState).toBeNull()
    expect(h.result.bargeResult).toMatchObject({
      intent: 'ANSWER_CALL',
      action: 'auto_answer',
      phrase: 'call utha lo',
    })
    const names = h.result.events.map((e) => e.name)
    expect(names).toContain('barge_in.detected')
    expect(names).toContain('tts.playback_halted')
    expect(names).toContain('barge_in.intent_classified')
    expect(names).toContain('call.auto_answer_triggered')
    expect(window.__audioInstances.at(-1).paused).toBe(true)
  })

  it('stops the recap only for a DISMISS_RECAP phrase', async () => {
    api.classifyIntent.mockResolvedValue({ intent: 'DISMISS_RECAP' })
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('full'))
    await h.actAsync(() => h.result.testPhrase('hold on one second'))
    expect(h.result.recapState).toBe(RECAP_STATE.HALTED)
    expect(h.result.phase).toBe(PHASE.RECAP) // still ringing — no auto-answer
    expect(h.result.bargeResult.action).toBe('stop_only')
    expect(h.result.events.some((e) => e.name === 'call.connected')).toBe(false)
  })

  it('halts playback for an IGNORE phrase but never answers', async () => {
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('full'))
    await h.actAsync(() => h.result.testPhrase('what was the rice quote again'))
    expect(h.result.recapState).toBe(RECAP_STATE.HALTED)
    expect(h.result.bargeResult.action).toBe('ignored')
    expect(h.result.phase).toBe(PHASE.RECAP)
  })

  it('ignores phrases when nothing is playing', async () => {
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.testPhrase('call utha lo'))
    expect(h.result.events.some((e) => e.name === 'barge_in.detected')).toBe(false)
    expect(h.result.bargeResult).toBeNull()
  })
})

// ── auto-pickup (India ring / mock caller) ───────────────────────────────────
describe('auto-pickup', () => {
  it('auto-starts the launch-chosen scenario when the recap text is ready', async () => {
    vi.useFakeTimers()
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.selectScenario('autoPickup'))
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(h.result.chosenMode).toBe('autoPickup')
    expect(h.result.recapState).toBe(RECAP_STATE.PLAYING)
  })

  it('network auto-pickup connects the call and starts the scripted caller ducked under the recap', async () => {
    vi.useFakeTimers()
    preloadMockLines.mockResolvedValue(MOCK_LINES)
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('autoPickup'))
    expect(h.result.recapState).toBe(RECAP_STATE.PLAYING)

    // ~30 s of ring → the network connects the call underneath the recap.
    await h.actAsync(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(h.result.callStateLabel).toBe('CONNECTED')
    expect(h.result.phase).toBe(PHASE.RECAP) // recap still playing on the private track
    const autoAnswer = h.result.events.find((e) => e.name === 'call.auto_answer_triggered')
    expect(autoAnswer.meta.mode).toBe('network')
    expect(h.result.events.some((e) => e.name === 'call.connected')).toBe(true)
    expect(h.result.events.some((e) => e.name === 'caller.mock_line')).toBe(true)
    expect(h.result.events.find((e) => e.name === 'caller.mock_line').meta.ducked).toBe(true)
    expect(h.result.call2Turns).toHaveLength(1)
    expect(h.result.call2Turns[0]).toMatchObject({ speaker: 'CALLER', mock: true })
    expect(api.recordTurn).toHaveBeenCalledWith(expect.objectContaining({ sessionId: SESSIONS.call2, speaker: 'CALLER' }))

    const [recapAudio, firstMockAudio] = window.__audioInstances
    // Recap ends naturally → the presenter goes live and the caller un-ducks.
    await h.actAsync(() => {
      recapAudio.onended()
    })
    expect(h.result.phase).toBe(PHASE.CONNECTED)
    expect(h.result.callStateLabel).toBe('CONNECTED')
    // Script advances: the next line plays at full volume once live.
    await h.actAsync(() => {
      firstMockAudio.onended()
    })
    await h.actAsync(async () => {
      await vi.advanceTimersByTimeAsync(2_800)
    })
    const mockLines = h.result.events.filter((e) => e.name === 'caller.mock_line')
    expect(mockLines.at(-1).meta.ducked).toBe(false)
    expect(h.result.call2Turns).toHaveLength(2)
  })

  it('filters mic echoes of scripted lines and records genuine presenter speech once connected', async () => {
    vi.useFakeTimers()
    api.getCapabilities.mockResolvedValue({ ready: true, stt: { enabled: true } })
    preloadMockLines.mockResolvedValue(MOCK_LINES)
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('autoPickup'))
    await h.actAsync(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(h.result.callStateLabel).toBe('CONNECTED')
    const mic = micHandles.at(-1)
    // The STT socket must report ready before transcripts are routed to the
    // auto-speech handler.
    await h.actAsync(() => {
      mic.ready()
    })

    // The presenter's mic hears the line that just played from the speakers.
    await h.actAsync(() => {
      mic.emitFinal('Hey — hello? Can you hear me? The network finally connected the call.')
    })
    expect(h.result.events.some((e) => e.name === 'caller.echo_filtered')).toBe(true)
    expect(api.recordTurn.mock.calls.filter((c) => c[0].speaker === 'USER')).toHaveLength(0)

    // Genuine speech while the recap plays → classified (ignored) then recorded.
    await h.actAsync(() => {
      mic.emitFinal('Got it, lock the basmati at 955')
    })
    expect(api.recordTurn).toHaveBeenCalledWith({
      sessionId: SESSIONS.call2,
      speaker: 'USER',
      text: 'Got it, lock the basmati at 955',
    })
    expect(h.result.call2Turns.some((t) => t.speaker === 'USER')).toBe(true)
  })
})

// ── end of call / wrap-up ────────────────────────────────────────────────────
describe('wrap-up', () => {
  it('endCall completes the demo and computes metrics', async () => {
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.startCall1())
    await h.actAsync(() => h.result.simulateDrop())
    await h.actAsync(() => h.result.continueToCallback())
    await h.actAsync(() => h.result.chooseRecapMode('full'))
    await h.actAsync(() => {
      window.__audioInstances.at(-1).onended()
    })
    await h.actAsync(() => h.result.endCall())
    expect(h.result.phase).toBe(PHASE.COMPLETED)
    expect(h.result.callStateLabel).toBe('COMPLETED')
    expect(api.endCallOne).toHaveBeenLastCalledWith({
      sessionId: SESSIONS.call2,
      callerId: CALLER.callerId,
      callerName: CALLER.name,
      interrupted: false,
    })
    expect(h.result.events.some((e) => e.name === 'call.completed')).toBe(true)
    expect(h.result.metrics).toMatchObject({
      freshnessChanged: true,
      autoAnswered: false,
      mockLines: 0,
      echoFiltered: 0,
      turns: 0,
    })
    expect(h.result.metrics.freshnessDetail).toContain('$955')
    expect(h.result.metrics.recapLatencyMs).toBeGreaterThanOrEqual(0)
  })

  it('fullReset returns to idle and clears all state', async () => {
    const h = await renderHook(useSimulation)
    await h.actAsync(() => h.result.startCall1())
    expect(h.result.phase).toBe(PHASE.CALL1)
    await h.actAsync(() => h.result.fullReset())
    expect(h.result.phase).toBe(PHASE.IDLE)
    expect(h.result.events).toHaveLength(0)
    expect(h.result.call1Turns).toHaveLength(0)
    expect(h.result.threadSummary).toBeNull()
    expect(api.resetDemo).toHaveBeenCalledTimes(2) // startCall1 + fullReset
  })
})