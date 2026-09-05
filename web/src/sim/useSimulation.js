import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api.js'
import {
  AUTO_PICKUP,
  CALLER,
  CLOCK,
  EVENT_KINDS,
  INTENT_LABELS,
  MOCK_CALLER,
  PRIVATE_TRACK_ID,
  RECAP_LANG,
  SESSIONS,
  SPEAKERS,
  STT_LANG,
} from './config.js'
import { startRingback, stopRingback } from './callerVoice.js'
import { isEchoOf, preloadMockLines } from './mockCaller.js'
import { micStreamSupported, startMicStream } from './userMic.js'

export const PHASE = {
  BOOT: 'boot', // probing the backend
  IDLE: 'idle', // ready to start / setup help shown
  CALL1: 'call1', // first live two-way conversation
  MEMORY: 'memory', // interrupted thread persisted, before the callback
  RECAP: 'recap', // next-morning callback: RINGING + private recap
  CONNECTED: 'connected', // second live conversation (after recap / barge-in)
  COMPLETED: 'completed', // evidence panel
}

export const RECAP_STATE = {
  READY: 'ready', // recap text ready, awaiting an option
  LOADING: 'loading', // Rime synthesizing
  PLAYING: 'playing',
  HALTED: 'halted', // barge-in stopped the whisper
  DONE: 'done', // recap finished naturally
  ERROR: 'error', // Rime unreachable (no fallback audio)
  NEEDS_GESTURE: 'needs_gesture', // browser blocked autoplay — tap to play
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

function pad2(n) {
  return String(n).padStart(2, '0')
}

function uid() {
  return globalThis.crypto && crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2)
}

function anchorDate(dayOffset, h, m, s) {
  const d = new Date()
  d.setDate(d.getDate() + dayOffset)
  d.setHours(h, m, s || 0, 0)
  return d
}

function splitSentences(text) {
  const parts = (text.match(/[^.!?]+[.!?]+/g) || [text])
    .map((p) => p.trim())
    .filter(Boolean)
  return parts.length ? parts : [text]
}

export function useSimulation() {
  // ── public state ────────────────────────────────────────────────────────────
  const [caps, setCaps] = useState(null)
  const [capsState, setCapsState] = useState('loading') // loading|ready|error
  const [capsError, setCapsError] = useState(null)
  const [phase, setPhase] = useState(PHASE.BOOT)
  const [recapState, setRecapState] = useState(null)
  const [callStateLabel, setCallStateLabel] = useState('IDLE')
  const [events, setEvents] = useState([])
  const [call1Turns, setCall1Turns] = useState([])
  const [call2Turns, setCall2Turns] = useState([])
  const [threadSummary, setThreadSummary] = useState(null)
  const [recap, setRecap] = useState(null)
  const [spokenIdx, setSpokenIdx] = useState(0)
  const [audioStatus, setAudioStatus] = useState('idle')
  const [listening, setListening] = useState(false)
  const [micError, setMicError] = useState(null)
  const [interimText, setInterimText] = useState('')
  const [bargeResult, setBargeResult] = useState(null)
  const [chosenMode, setChosenMode] = useState(null) // 'full' | 'barge' | 'autoPickup'
  const [pickupCountdownS, setPickupCountdownS] = useState(null) // seconds until network auto-pickup (mock caller option)
  const [mockLineSpoken, setMockLineSpoken] = useState(null) // { index, text, ducked } while a scripted Z line is audible
  const [mockError, setMockError] = useState(null)
  const [memoryBusy, setMemoryBusy] = useState(false)
  const [recordingSpeaker, setRecordingSpeaker] = useState(null) // 'USER' | 'CALLER' | null
  const [metrics, setMetrics] = useState(null)
  const [error, setError] = useState(null)
  // Website copy is always English (no EN/HI switch) — the Hinglish lives on
  // the voice layer only (STT_LANG / RECAP_LANG in config.js).
  const lang = 'en'
  // Test case chosen on the launch screen, before call 1 is recorded.
  const [chosenScenario, setChosenScenario] = useState(null) // 'full' | 'barge' | 'autoPickup' | null

  // ── mutable session plumbing ────────────────────────────────────────────────
  const aliveRef = useRef(true)
  const sessionRef = useRef({ mic: null, audioEl: null, audioUrl: null, listeningFor: null })
  const recordingRef = useRef(null) // { speaker, sessionId, texts: [] } while a turn is being recorded
  const clockRef = useRef({ anchor: new Date(), perf: performance.now() })
  const anchorsRef = useRef({})
  const eventsRef = useRef([])
  const handledBargeRef = useRef(false)
  const bargeArmedRef = useRef(false)
  const scriptCancelRef = useRef(false)
  const chosenModeRef = useRef(null)
  const recapStateRef = useRef(null)
  const scenarioRef = useRef(null)
  const autoRanRef = useRef(false) // has the launch-chosen scenario been auto-started this callback?
  const resumeRef = useRef(null) // resumes recap playback on a fresh user gesture
  const chooseRecapModeRef = useRef(null)
  // Auto-pickup (mock caller) plumbing — India ring behaviour.
  const pickupRef = useRef(null) // { deadline, timer } — network connects the call after ~30 s of ring
  const pickedUpRef = useRef(false) // the call got connected while the recap plays/stays ready
  const connectedEventRef = useRef(false) // has a call.connected event been pushed for this callback take?
  const mockRef = useRef({
    lines: [], // [{ index, text, gapMs, objectUrl }] prepared by preloadMockLines
    urls: [], // object URLs to revoke on teardown
    idx: 0,
    started: false,
    pending: false, // pickup happened before the lines finished synthesizing
    ducked: true, // caller voice reduced while the recap whisper plays
    el: null, // currently playing Audio element
    timer: null, // inter-line gap timer
    recent: [], // [{ text, untilMs }] echo-filter window for the line on the speakers
  })
  const doPickupRef = useRef(null)
  const liveNowRef = useRef(null)
  const handleAutoSpeechRef = useRef(null)

  // Mirror phase-critical values into refs so async handlers always read the
  // latest value instead of a stale render closure.
  useEffect(() => {
    recapStateRef.current = recapState
  }, [recapState])
  useEffect(() => {
    chosenModeRef.current = chosenMode
  }, [chosenMode])

  // The launch screen asks for the test case *before* recording; carry it into
  // the callback stage and auto-start it the moment the recap text is ready.
  const selectScenario = useCallback((scenario) => {
    scenarioRef.current = scenario
    setChosenScenario(scenario)
  }, [])

  useEffect(() => {
    if (phase !== PHASE.RECAP) return
    if (recapState !== RECAP_STATE.READY || !recap) return
    const scenario = scenarioRef.current
    if (!scenario || autoRanRef.current) return
    autoRanRef.current = true
    if (chooseRecapModeRef.current) chooseRecapModeRef.current(scenario)
  }, [phase, recapState, recap])

  const pushEvent = useCallback((name, detail = '', meta = {}) => {
    const clock = clockRef.current
    const ts = new Date(clock.anchor.getTime() + (performance.now() - clock.perf))
    const entry = {
      id: uid(),
      name,
      kind: EVENT_KINDS[name] || 'action',
      detail,
      meta,
      ts: ts.toISOString(),
      tsLabel: `${pad2(ts.getHours())}:${pad2(ts.getMinutes())}:${pad2(ts.getSeconds())}.${pad2(Math.floor(ts.getMilliseconds() / 10))}`,
      epoch: ts.getTime(),
    }
    eventsRef.current = [...eventsRef.current, entry]
    setEvents(eventsRef.current)
  }, [])

  const setClock = useCallback((label, dayOffset, { hour, minute, second }) => {
    clockRef.current = {
      anchor: anchorDate(dayOffset, hour, minute, second || 0),
      perf: performance.now(),
      label,
    }
  }, [])

  const remember = useCallback((name) => {
    const now = performance.now()
    anchorsRef.current[name] = now
    return now
  }, [])

  const deltaSince = useCallback((name) => {
    const anchor = anchorsRef.current[name]
    return anchor == null ? null : Math.max(0, Math.round(performance.now() - anchor))
  }, [])

  const clearAll = useCallback(() => {
    aliveRef.current = false
    stopRingback()
    stopMicSafe()
    teardownRecapAudio()
    stopMockCaller()
    clearPickupTimer()
    eventsRef.current = []
    anchorsRef.current = {}
    handledBargeRef.current = false
    bargeArmedRef.current = false
    scriptCancelRef.current = true
    pickedUpRef.current = false
    connectedEventRef.current = false
    pickupRef.current = null
    chosenModeRef.current = null
    recapStateRef.current = null
    setPhase(PHASE.IDLE)
    setRecapState(null)
    setCallStateLabel('IDLE')
    setEvents([])
    setCall1Turns([])
    setCall2Turns([])
    setThreadSummary(null)
    setRecap(null)
    setSpokenIdx(0)
    setAudioStatus('idle')
    setBargeResult(null)
    setChosenMode(null)
    setPickupCountdownS(null)
    setMockLineSpoken(null)
    setMockError(null)
    setMemoryBusy(false)
    setMetrics(null)
    setError(null)
    setInterimText('')
    setListening(false)
    setRecordingSpeaker(null)
    autoRanRef.current = false
    resumeRef.current = null
    setTimeout(() => {
      aliveRef.current = true
      scriptCancelRef.current = false
    }, 0)
  }, [])

  // Referenced by clearAll — defined later; indirection keeps single-pass deps.
  function stopMicSafe() {
    const s = sessionRef.current
    if (s.mic) {
      try {
        s.mic.stop()
      } catch {
        /* noop */
      }
      s.mic = null
    }
    s.listeningFor = null
    recordingRef.current = null
    setListening(false)
    setInterimText('')
    setRecordingSpeaker(null)
  }

  const teardownRecapAudio = useCallback(() => {
    const s = sessionRef.current
    if (s.audioEl) {
      try {
        s.audioEl.pause()
        s.audioEl.onended = null
        s.audioEl.ontimeupdate = null
      } catch {
        /* noop */
      }
      s.audioEl = null
    }
    if (s.audioUrl) {
      URL.revokeObjectURL(s.audioUrl)
      s.audioUrl = null
    }
  }, [])

  const stopMic = useCallback(() => {
    const s = sessionRef.current
    if (s.mic) {
      try {
        s.mic.stop()
      } catch {
        /* noop */
      }
      s.mic = null
    }
    s.listeningFor = null
    recordingRef.current = null
    setListening(false)
    setInterimText('')
    setRecordingSpeaker(null)
  }, [])

  // ── live turn recording (both speakers share the browser mic) ──────────────
  const commitTurn = useCallback(
    async (speaker, text, sessionId, { mock = false } = {}) => {
      const cleaned = (text || '').trim()
      if (!cleaned) return
      const label = SPEAKERS[speaker]?.label || speaker
      const turn = { id: uid(), speaker, text: cleaned, live: false, mock }
      if (sessionId === SESSIONS.call2) {
        setCall2Turns((prev) => [...prev, turn])
      } else {
        setCall1Turns((prev) => [...prev, turn])
      }
      pushEvent('turn.recorded', `${label}${mock ? ' · scripted' : ''}: ${cleaned}`, {
        session_id: sessionId,
        speaker,
        chars: cleaned.length,
        source: mock ? 'mock' : 'live',
      })
      try {
        await api.recordTurn({ sessionId, speaker, text: cleaned })
      } catch {
        /* memory is best-effort during the live call */
      }
    },
    [pushEvent],
  )

  const startTurn = useCallback(
    async (speaker, sessionId) => {
      if (!caps || !caps.stt || !caps.stt.enabled) {
        setMicError('Live mic needs the backend running with USE_MOCKS=false and a Deepgram key.')
        return null
      }
      if (!micStreamSupported()) {
        setMicError('This browser cannot capture the microphone.')
        return null
      }
      stopMic()
      setMicError(null)
      recordingRef.current = { speaker, sessionId, texts: [] }
      try {
        const handle = await startMicStream({
          sessionId,
          speaker,
          language: STT_LANG, // Hinglish voice input (Nova-3 hi → romanized on the backend)
          onReady: () => {
            sessionRef.current.listeningFor = { kind: 'turn', speaker, sessionId }
            setListening(true)
            setRecordingSpeaker(speaker)
          },
          onTranscript: (m) => {
            if (!m.isFinal) {
              setInterimText(m.text)
              return
            }
            setInterimText('')
            const rec = recordingRef.current
            if (rec && rec.speaker === speaker && rec.sessionId === sessionId) {
              rec.texts.push(m.text)
            }
          },
          onError: (e) => {
            setMicError(e.message || 'Speech-to-text error')
            setListening(false)
            setRecordingSpeaker(null)
          },
        })
        sessionRef.current.mic = handle
        return handle
      } catch (err) {
        recordingRef.current = null
        setMicError(err.message || 'Could not access the microphone')
        return null
      }
    },
    [caps, stopMic],
  )

  // Stop recording and commit the accumulated segment as one stored turn.
  const endTurn = useCallback(() => {
    const rec = recordingRef.current
    stopMic()
    if (!rec) return
    const text = (rec.texts || []).join(' ').trim()
    if (text) commitTurn(rec.speaker, text, rec.sessionId)
  }, [commitTurn, stopMic])

  const handleBargeRef = useRef(null)

  const startMic = useCallback(
    async (forWhat, sessionId) => {
      if (!caps || !caps.stt || !caps.stt.enabled) {
        setMicError('Live mic needs the backend running with USE_MOCKS=false and a Deepgram key. Typed replies still work.')
        return null
      }
      if (!micStreamSupported()) {
        setMicError('This browser cannot capture the microphone. Typed replies still work.')
        return null
      }
      stopMic()
      setMicError(null)
      try {
        const handle = await startMicStream({
          sessionId,
          language: STT_LANG, // Hinglish voice input (Nova-3 hi → romanized on the backend)
          onReady: () => {
            sessionRef.current.listeningFor = forWhat
            setListening(true)
          },
          onTranscript: (m) => {
            if (!m.isFinal) {
              setInterimText(m.text)
              return
            }
            setInterimText('')
            const mode = sessionRef.current.listeningFor
            if (mode === 'barge' && handleBargeRef.current) {
              handleBargeRef.current(m.text)
            } else if (mode === 'auto' && handleAutoSpeechRef.current) {
              handleAutoSpeechRef.current(m.text)
            }
          },
          onError: (e) => {
            setMicError(e.message || 'Speech-to-text error')
            setListening(false)
          },
        })
        sessionRef.current.mic = handle
        return handle
      } catch (err) {
        setMicError(err.message || 'Could not access the microphone')
        return null
      }
    },
    [caps, stopMic],
  )

  // ── Call one (yesterday, live two-way) ─────────────────────────────────────
  const simulateDropRef = useRef(null)
  const simulateDrop = useCallback(async () => {
    if (!aliveRef.current) return
    scriptCancelRef.current = true
    stopMic()
    stopRingback()
    pushEvent('call.disconnect_detected', 'caller=Z · no closing turn · mid-sentence', { since_event: 'call.connected', delta_ms: deltaSince('call.connected') ?? 0 })
    setCallStateLabel('DISCONNECTED')
    setPhase(PHASE.MEMORY)
    setMemoryBusy(true)
    pushEvent('thread.marked_interrupted', 'persisted last state · is_interrupted=true')
    try {
      const summary = await api.endCallOne({
        sessionId: SESSIONS.call1,
        callerId: CALLER.callerId,
        callerName: CALLER.name,
        interrupted: true,
      })
      if (aliveRef.current) setThreadSummary(summary)
    } catch (err) {
      if (aliveRef.current) setError(`Memory store error: ${err.message}`)
    } finally {
      if (aliveRef.current) setMemoryBusy(false)
    }
  }, [deltaSince, pushEvent, stopMic])
  simulateDropRef.current = simulateDrop

  const startCall1 = useCallback(async () => {
    setError(null)
    setMicError(null)
    scriptCancelRef.current = false
    // Clean baseline between takes so the stored thread is always fresh.
    try {
      await api.resetDemo({ callerId: CALLER.callerId, sessionIds: [SESSIONS.call1, SESSIONS.call2] })
    } catch {
      /* offline reset is fine */
    }
    setClock('Yesterday · call 1', -1, CLOCK.call1Start)
    setCallStateLabel('CONNECTED')
    setPhase(PHASE.CALL1)
    setCall1Turns([])
    remember('call.connected')
    pushEvent('call.connected', 'caller=Z · session call-1 · live two-way call begins')
    if (!caps || !caps.stt || !caps.stt.enabled) {
      setMicError('Deepgram STT unavailable — check the backend / .env (USE_MOCKS=false + DEEPGRAM_API_KEY).')
    }
  }, [caps, pushEvent, remember, setClock])

  // ── Callback recap (next morning) ───────────────────────────────────────────
  const continueToCallback = useCallback(async () => {
    if (!aliveRef.current) return
    setError(null)
    setMicError(null)
    setClock('Next morning · call 2', 0, CLOCK.call2Start)
    setCallStateLabel('RINGING')
    setPhase(PHASE.RECAP)
    setRecapState(RECAP_STATE.READY)
    setChosenMode(null)
    setBargeResult(null)
    setCall2Turns([])
    handledBargeRef.current = false
    bargeArmedRef.current = false
    scriptCancelRef.current = false
    chosenModeRef.current = null
    recapStateRef.current = RECAP_STATE.READY
    autoRanRef.current = false
    resumeRef.current = null
    pickedUpRef.current = false
    connectedEventRef.current = false
    clearPickupTimer()
    stopMockCaller()
    // The network auto-pickup clock starts the moment Z's call rings in
    // (India ring behaviour) — the mock-caller option connects at this deadline.
    pickupRef.current = {
      deadline: performance.now() + AUTO_PICKUP.ringDelayS * 1000,
      timer: null,
    }
    setPickupCountdownS(null)
    setMockLineSpoken(null)
    setMockError(null)
    teardownRecapAudio()
    setAudioStatus('idle')
    setSpokenIdx(0)
    setRecap(null)
    startRingback()
    remember('call.inbound_ring')
    pushEvent('call.inbound_ring', `caller=${CALLER.name} · ${CALLER.number}`)
    pushEvent('thread.match_found', 'confidence=1.00 · caller=Z · thread=z-contact-01', { since_event: 'call.inbound_ring', delta_ms: deltaSince('call.inbound_ring') ?? 0 })
    remember('match')
    pushEvent('recap.generation_started', 'stored thread → freshness → Rime text', { since_event: 'thread.match_found', delta_ms: deltaSince('match') ?? 0 })
    try {
      const payload = await api.buildRecap({
        callerId: CALLER.callerId,
        sessionId: SESSIONS.call2,
        ringWindowS: AUTO_PICKUP.ringDelayS,
        language: RECAP_LANG, // Hinglish recap (backend writes Hinglish frames)
      })
      if (!aliveRef.current) return
      const checks = payload.freshness?.results || []
      for (const f of checks.filter((x) => x.status === 'CHANGED')) {
        pushEvent('freshness.discrepancy_found', `${f.label}: ${f.cached_value} → ${f.live_value}`, { key: f.key, cached: f.cached_value, live: f.live_value, latency_ms: f.latency_ms })
      }
      for (const f of checks.filter((x) => x.status === 'UNAVAILABLE')) {
        pushEvent('freshness.discrepancy_found', `${f.label}: verification unavailable`, { key: f.key, status: 'UNAVAILABLE', latency_ms: f.latency_ms })
      }
      pushEvent('recap.text_ready', 'Rime prompting-guide validated', { sentences: splitSentences(payload.text).length, metrics: payload.metrics })
      setRecap({ ...payload, sentences: splitSentences(payload.text) })
      setSpokenIdx(0)
      setRecapState(RECAP_STATE.READY)
    } catch (err) {
      if (aliveRef.current) {
        setRecapState(RECAP_STATE.ERROR)
        setError(`Recap generation failed: ${err.message}`)
      }
    }
  }, [deltaSince, pushEvent, remember, setClock])

  const playRecapAudio = useCallback(async () => {
    const current = recap
    if (!current) return
    setAudioStatus('loading')
    setRecapState(RECAP_STATE.LOADING)
    recapStateRef.current = RECAP_STATE.LOADING
    let objectUrl
    let fetchMs = 0
    try {
      const fetched = await api.fetchRimeAudio(current.text, {
        trackId: PRIVATE_TRACK_ID,
        speaker: current.speaker,
        model: current.model,
        timeScaleFactor: current.time_scale_factor,
        lang: RECAP_LANG, // 'hi' — Hindi accent voice (nadi) on the Rime side
      })
      objectUrl = fetched.objectUrl
      fetchMs = fetched.fetchMs
    } catch (err) {
      if (aliveRef.current) {
        setAudioStatus('error')
        setRecapState(RECAP_STATE.ERROR)
        recapStateRef.current = RECAP_STATE.ERROR
        setError(`Rime did not return audio: ${err.message}`)
        // Mock run: if the network already picked up and the recap cannot play,
        // drop the ducking and go live with the scripted caller instead.
        if (chosenModeRef.current === 'autoPickup' && pickedUpRef.current) {
          liveNowRef.current?.({ from: 'recap-error' })
        }
      }
      return
    }
    if (!aliveRef.current) {
      URL.revokeObjectURL(objectUrl)
      return
    }
    teardownRecapAudio()
    const audio = new Audio(objectUrl)
    sessionRef.current.audioEl = audio
    sessionRef.current.audioUrl = objectUrl
    const sentences = current.sentences || []
    const lengths = sentences.map((s) => s.length)
    const totalChars = lengths.reduce((a, b) => a + b, 0) || 1
    // Rime may return a streaming WAV whose duration is unknown until fully
    // buffered — estimate from the character count so captions stay in sync.
    const estimatedMs = Math.max(2000, (totalChars / 13) * 1000)
    const playbackStart = performance.now()
    const progress = () => {
      const d = audio.duration
      if (Number.isFinite(d) && d > 0) return Math.min(1, audio.currentTime / d)
      return Math.min(1, (performance.now() - playbackStart) / estimatedMs)
    }
    audio.ontimeupdate = () => {
      const target = progress() * totalChars
      let acc = 0
      let idx = 0
      for (let i = 0; i < sentences.length; i += 1) {
        acc += lengths[i]
        if (target <= acc) {
          idx = i
          break
        }
        idx = i
      }
      setSpokenIdx(idx)
    }
    audio.onended = () => {
      if (!aliveRef.current) return
      setRecapState(RECAP_STATE.DONE)
      recapStateRef.current = RECAP_STATE.DONE
      setAudioStatus('idle')
      setSpokenIdx(Math.max(0, sentences.length - 1))
      // A finished recap no longer needs the barge-in mic.
      if (sessionRef.current.listeningFor === 'barge') stopMic()
      // Auto-pickup mock run: if the network already connected the call, the
      // presenter is now live with the scripted caller.
      if (chosenModeRef.current === 'autoPickup' && pickedUpRef.current) {
        liveNowRef.current?.({ from: 'recap-end' })
      }
    }
    // Everything that must happen once playback actually started (status,
    // first-audio event, mock-caller join) — shared by the direct play and the
    // gesture-retry path below.
    const afterStart = async () => {
      if (!aliveRef.current) return
      setAudioStatus('playing')
      setRecapState(RECAP_STATE.PLAYING)
      recapStateRef.current = RECAP_STATE.PLAYING
      pushEvent('recap.tts_first_audio', `Δ ${deltaSince('match') ?? '?'}ms from match`, { since_event: 'thread.match_found', delta_ms: deltaSince('match') ?? null, rime_fetch_ms: Math.round(fetchMs) })
      // If the network pickup already fired while Rime was fetching, let the
      // scripted caller join (ducked) now that the recap is actually playing.
      if (chosenModeRef.current === 'autoPickup' && pickedUpRef.current) {
        kickMockCaller()
      }
    }
    try {
      await audio.play()
      await afterStart()
    } catch (err) {
      // Autoplay blocked: the Rime synthesis outlived the click's ~5s
      // user-activation window, so the browser refused play().  Keep the audio
      // warm, retry on the next interaction, and expose a visible play button
      // (a fresh gesture always starts playback).  No silent TTS substitution.
      if (!aliveRef.current) return
      setAudioStatus('blocked')
      setRecapState(RECAP_STATE.NEEDS_GESTURE)
      recapStateRef.current = RECAP_STATE.NEEDS_GESTURE
      const retry = () => {
        cleanup()
        resume()
      }
      const cleanup = () => {
        window.removeEventListener('pointerdown', retry, true)
        window.removeEventListener('keydown', retry, true)
      }
      const resume = async () => {
        const el = sessionRef.current.audioEl
        if (!el || !aliveRef.current) return
        try {
          await el.play()
          await afterStart()
        } catch {
          /* still blocked — the button stays visible */
        }
      }
      resumeRef.current = resume
      window.addEventListener('pointerdown', retry, true)
      window.addEventListener('keydown', retry, true)
    }
  }, [recap, teardownRecapAudio, pushEvent, deltaSince, stopMic])

  const chooseRecapMode = useCallback(
    async (mode) => {
      setChosenMode(mode)
      chosenModeRef.current = mode
      handledBargeRef.current = false
      setBargeResult(null)
      setError(null)
      setMockError(null)
      if (mode === 'autoPickup') {
        // Mock caller / India auto-pickup: the recap plays on the private
        // track, the network connects the call ~30 s into the ring, and the
        // scripted caller then joins at reduced volume under the recap.
        bargeArmedRef.current = true
        armPickupCountdown()
        await playRecapAudio()
        if (!aliveRef.current) return
        // Arm the presenter's mic for replies / commands once the recap is
        // actually playing (the auto-pickup handler also opens it if needed).
        if (!sessionRef.current.mic && caps && caps.stt && caps.stt.enabled) {
          await startMic('auto', SESSIONS.call2)
        } else if (!caps || !caps.stt || !caps.stt.enabled) {
          setMicError('Mic unavailable for your replies — the scripted caller and recap still play. Live STT needs USE_MOCKS=false + a DEEPGRAM_API_KEY.')
        }
        preloadMockCallerAudios() // background — lines start after pickup
        return
      }
      bargeArmedRef.current = mode === 'barge'
      await playRecapAudio()
      if (mode === 'barge') {
        if (caps && caps.stt && caps.stt.enabled) {
          await startMic('barge', SESSIONS.call2)
        } else {
          setMicError('Mic unavailable — use "Test barge-in phrase" while the recap plays, or choose the other option.')
        }
      }
    },
    [caps, playRecapAudio, startMic],
  )
  chooseRecapModeRef.current = chooseRecapMode

  // Turn full-duplex listening on/off mid-recap without re-playing audio.
  const armBargeMic = useCallback(async () => {
    if (!aliveRef.current) return
    if (chosenModeRef.current === 'autoPickup') {
      // Mock run — resume the presenter's voice capture after it was muted.
      if (caps && caps.stt && caps.stt.enabled) {
        await startMic('auto', SESSIONS.call2)
      } else {
        setMicError('Mic unavailable — the scripted caller and recap still play.')
      }
      return
    }
    bargeArmedRef.current = true
    setChosenMode('barge')
    chosenModeRef.current = 'barge'
    if (caps && caps.stt && caps.stt.enabled) {
      await startMic('barge', SESSIONS.call2)
    } else {
      setMicError('Mic unavailable — use the phrase-test buttons while the recap plays.')
    }
  }, [caps, startMic])

  const replayRecap = useCallback(async () => {
    handledBargeRef.current = false
    bargeArmedRef.current = bargeArmedRef.current
    setBargeResult(null)
    setSpokenIdx(0)
    await playRecapAudio()
  }, [playRecapAudio])

  // ── Barge-in handling (the demo's second hard voice problem) ───────────────
  const handleBargeUtterance = useCallback(
    async (rawText) => {
      const text = (rawText || '').trim()
      if (!aliveRef.current || !text || handledBargeRef.current) return
      const s = sessionRef.current
      if (!s.audioEl || s.audioEl.paused || s.audioEl.ended) return
      if (!bargeArmedRef.current) return
      handledBargeRef.current = true
      remember('barge_detected')
      pushEvent('barge_in.detected', `phrase="${text}"`, { since_event: 'recap.tts_first_audio', delta_ms: deltaSince('barge_detected') ?? 0 })
      const haltStart = performance.now()
      try {
        s.audioEl.pause()
      } catch {
        /* noop */
      }
      const haltedMs = Math.max(0, Math.round(performance.now() - haltStart))
      setRecapState(RECAP_STATE.HALTED)
      setAudioStatus('idle')
      pushEvent('tts.playback_halted', `Δ ${haltedMs}ms from barge-in`, { since_event: 'barge_in.detected', delta_ms: haltedMs })

      let intent = 'DISMISS_RECAP'
      try {
        const result = await api.classifyIntent(text)
        intent = result.intent || intent
      } catch {
        intent = 'DISMISS_RECAP' // server offline → safest: stop only
      }
      if (!aliveRef.current) return
      const action = INTENT_LABELS[intent] || intent
      pushEvent('barge_in.intent_classified', `intent=${action}`, { intent, raw: text })
      setBargeResult({ intent, action, phrase: text, haltedMs })

      if (intent === 'ANSWER_CALL') {
        remember('call.auto_answer_triggered')
        pushEvent('call.auto_answer_triggered', `caller=${CALLER.name} · auto-answered from barge-in`, { since_event: 'barge_in.intent_classified', delta_ms: deltaSince('call.auto_answer_triggered') ?? 0 })
        await advanceToConnectedRef.current?.()
      }
    },
    [deltaSince, pushEvent, remember],
  )
  handleBargeRef.current = handleBargeUtterance

  const testPhrase = useCallback(
    async (text) => {
      if (!aliveRef.current || phase !== PHASE.RECAP) return
      const s = sessionRef.current
      if (!s.audioEl || s.audioEl.paused || s.audioEl.ended) return
      bargeArmedRef.current = true
      if (chosenModeRef.current === 'autoPickup') {
        // Mock run — phrase test behaves like live speech (only recognised
        // commands interrupt; other words are replies that the recap ignores).
        if (handleAutoSpeechRef.current) await handleAutoSpeechRef.current(text)
        return
      }
      await handleBargeUtterance(text)
    },
    [handleAutoSpeechRef, handleBargeUtterance, phase],
  )

  // ── Auto-pickup + scripted mock caller (India ring behaviour) ──────────────
  // In India the network connects an incoming call by itself after ~30 s of
  // ringing (AUTO_PICKUP.ringDelayS). The recap keeps playing on the private
  // track when that happens, and a scripted (mock) caller joins on the caller
  // lane at reduced volume so the recap stays intelligible. The mock lines are
  // authored text — they are recorded straight to thread memory as CALLER turns
  // and never read back from the mic; only the presenter's voice is transcribed
  // (and echoes of the speaker output are filtered out).

  function clearPickupTimer() {
    const p = pickupRef.current
    if (p && p.timer) {
      clearInterval(p.timer)
      p.timer = null
    }
    setPickupCountdownS(null)
  }

  // Arm the network auto-pickup clock (deadline was set when the ring began).
  function armPickupCountdown() {
    const p = pickupRef.current
    if (!p || p.timer || pickedUpRef.current) return
    const tick = () => {
      const remainingMs = p.deadline - performance.now()
      if (remainingMs <= 0) {
        clearInterval(p.timer)
        p.timer = null
        setPickupCountdownS(null)
        if (doPickupRef.current) doPickupRef.current()
      } else {
        setPickupCountdownS(Math.max(1, Math.ceil(remainingMs / 1000)))
      }
    }
    tick()
    p.timer = setInterval(tick, 250)
  }

  function stopMockCaller() {
    const m = mockRef.current
    clearTimeout(m.timer)
    m.timer = null
    if (m.el) {
      try {
        m.el.pause()
      } catch {
        /* noop */
      }
      m.el.onended = null
      m.el = null
    }
    m.started = false
    m.idx = 0
    m.pending = false
    m.recent = []
    setMockLineSpoken(null)
    m.urls.forEach((url) => {
      try {
        URL.revokeObjectURL(url)
      } catch {
        /* noop */
      }
    })
    m.urls = []
    m.lines = []
  }

  function mockVolume() {
    return mockRef.current.ducked ? MOCK_CALLER.duckedVolume : MOCK_CALLER.fullVolume
  }

  function setMockDucked(ducked) {
    mockRef.current.ducked = Boolean(ducked)
    if (mockRef.current.el) mockRef.current.el.volume = mockVolume()
  }

  function scheduleNextMockLine(nextIdx, gapMs) {
    const m = mockRef.current
    clearTimeout(m.timer)
    m.timer = setTimeout(() => playMockLineAt(nextIdx), Math.max(0, gapMs || 0))
  }

  function playMockLineAt(index) {
    const m = mockRef.current
    if (!aliveRef.current || !m.lines) return
    if (index >= m.lines.length) {
      m.el = null
      m.started = false
      setMockLineSpoken(null)
      return
    }
    const line = m.lines[index]
    m.idx = index + 1
    if (!line || !line.objectUrl) {
      scheduleNextMockLine(m.idx, 700)
      return
    }
    try {
      const audio = new Audio(line.objectUrl)
      audio.volume = mockVolume()
      m.el = audio
      // Track the line in the echo window while it is audible from the speakers.
      const now = performance.now()
      m.recent = m.recent.filter((r) => now <= r.untilMs)
      m.recent.push({
        text: line.text,
        untilMs: now + line.text.length * 85 + 1400,
      })
      setMockLineSpoken({ index, text: line.text, ducked: m.ducked })
      commitTurn('CALLER', line.text, SESSIONS.call2, { mock: true })
      pushEvent('caller.mock_line', `${CALLER.name} · scripted${m.ducked ? ' (ducked under recap)' : ''}: “${line.text}”`, {
        speaker: 'CALLER',
        mock: true,
        ducked: m.ducked,
        chars: line.text.length,
      })
      audio.onended = () => {
        if (m.el === audio) m.el = null
        setMockLineSpoken(null)
        if (!aliveRef.current) return
        scheduleNextMockLine(m.idx, line.gapMs ?? 0)
      }
      audio.play().catch(() => {
        if (m.el === audio) m.el = null
        scheduleNextMockLine(m.idx, 700)
      })
    } catch {
      scheduleNextMockLine(m.idx, 700)
    }
  }

  // Start the scripted caller, but never over a recap that is still loading or
  // over dead air — only once the recap is actually playing (or is gone).
  function kickMockCaller() {
    const m = mockRef.current
    if (!aliveRef.current || !pickedUpRef.current) return
    if (!m.lines.length || recapStateRef.current === RECAP_STATE.LOADING || recapStateRef.current === RECAP_STATE.READY) {
      m.pending = true
      return
    }
    m.pending = false
    if (!m.started) {
      m.started = true
      playMockLineAt(m.idx)
    }
  }

  // The presenter interrupted mid-line (or answered) — stop the current line and
  // move the script along after a short breath so the presenter can talk.
  function skipCurrentMockLine() {
    const m = mockRef.current
    clearTimeout(m.timer)
    if (m.el) {
      try {
        m.el.pause()
      } catch {
        /* noop */
      }
      m.el = null
      setMockLineSpoken(null)
    }
    scheduleNextMockLine(m.idx, 1400)
  }

  async function preloadMockCallerAudios() {
    const m = mockRef.current
    // Scripted Z always speaks Hinglish (fixed — no language switch).
    const script = MOCK_CALLER.lines
    try {
      const lines = await preloadMockLines(script, {
        speaker: MOCK_CALLER.speaker,
        model: MOCK_CALLER.model || undefined,
        timeScaleFactor: MOCK_CALLER.timeScaleFactor,
        lang: MOCK_CALLER.language,
      })
      if (!aliveRef.current) {
        lines.forEach((l) => URL.revokeObjectURL(l.objectUrl))
        return
      }
      m.lines = lines
      m.urls = lines.map((l) => l.objectUrl)
      if (!lines.length && aliveRef.current) {
        // Every scripted line failed to synthesise — say so instead of
        // leaving the mock caller silently mute.
        setMockError(
          'Mock caller voice could not be prepared (Rime unavailable). The recap still plays; the scripted Z lines are skipped.'
        )
      }
      if (m.pending) kickMockCaller()
    } catch (err) {
      if (aliveRef.current) {
        setMockError(`Mock caller voice could not be prepared: ${err.message}`)
      }
    }
  }

  // Network auto-pickup fires after ~30 s of ring (India). If the recap is
  // still playing it keeps playing and the scripted caller joins ducked.
  const doPickup = useCallback(async () => {
    if (!aliveRef.current || pickedUpRef.current) return
    pickedUpRef.current = true
    clearPickupTimer()
    stopRingback()
    remember('auto_pickup')
    pushEvent('call.auto_answer_triggered', `network auto-pickup — ring exceeded ${AUTO_PICKUP.ringDelayS}s`, {
      mode: 'network',
      ring_delay_s: AUTO_PICKUP.ringDelayS,
      since_event: 'call.inbound_ring',
      delta_ms: deltaSince('auto_pickup') ?? 0,
    })
    pushEvent('call.connected', `auto-connected after ${AUTO_PICKUP.ringDelayS}s ring — recap keeps playing on your private track`, { mode: 'network' })
    connectedEventRef.current = true
    setCallStateLabel('CONNECTED')
    const rs = recapStateRef.current
    if (rs === RECAP_STATE.DONE || rs === RECAP_STATE.ERROR || rs === RECAP_STATE.HALTED) {
      // Nothing left to hear — go straight to the live conversation.
      if (liveNowRef.current) liveNowRef.current({ from: 'pickup' })
      return
    }
    // Recap is ready, loading or already playing: the call connects underneath
    // it and the scripted caller joins at reduced volume when audio starts.
    setMockDucked(true)
    kickMockCaller()
    if (!sessionRef.current.mic) await startMic('auto', SESSIONS.call2)
  }, [deltaSince, pushEvent, remember, startMic])

  // Enter the connected live stage (phase CONNECTED) with the presenter's mic
  // auto-armed and the scripted caller continuing at normal volume.
  const liveNow = useCallback(
    async ({ from = 'auto' } = {}) => {
      if (!aliveRef.current) return
      pickedUpRef.current = true
      clearPickupTimer()
      stopRingback()
      setMockDucked(false)
      teardownRecapAudio()
      setRecapState(null)
      recapStateRef.current = null
      setAudioStatus('idle')
      setSpokenIdx(0)
      setCallStateLabel('CONNECTED')
      setPhase(PHASE.CONNECTED)
      if (!connectedEventRef.current) {
        pushEvent('call.connected', 'caller=Z · you are live with the scripted caller', { mode: from === 'barge' ? 'barge' : 'manual' })
        connectedEventRef.current = true
      }
      kickMockCaller()
      if (!sessionRef.current.mic) await startMic('auto', SESSIONS.call2)
    },
    [pushEvent, startMic, teardownRecapAudio],
  )

  // A recognised interrupt while the recap plays in the mock run. Only explicit
  // voice commands stop the recap — ordinary replies never do (unlike option A,
  // where any live speech is treated as a barge-in).
  async function stopRecapForBarge(rawText, intent) {
    if (!aliveRef.current || !rawText) return
    const s = sessionRef.current
    remember('barge_detected')
    pushEvent('barge_in.detected', `phrase="${rawText}"`, { since_event: 'recap.tts_first_audio', delta_ms: deltaSince('barge_detected') ?? 0 })
    const haltStart = performance.now()
    if (s.audioEl) {
      try {
        s.audioEl.pause()
      } catch {
        /* noop */
      }
    }
    const haltedMs = Math.max(0, Math.round(performance.now() - haltStart))
    setRecapState(RECAP_STATE.HALTED)
    recapStateRef.current = RECAP_STATE.HALTED
    setAudioStatus('idle')
    pushEvent('tts.playback_halted', `Δ ${haltedMs}ms from barge-in`, { since_event: 'barge_in.detected', delta_ms: haltedMs })
    const action = INTENT_LABELS[intent] || intent
    pushEvent('barge_in.intent_classified', `intent=${action}`, { intent, raw: rawText })
    setBargeResult({ intent, action, phrase: rawText, haltedMs })
    if (intent === 'ANSWER_CALL') {
      if (!pickedUpRef.current) {
        pickedUpRef.current = true
        clearPickupTimer()
        remember('call.auto_answer_triggered')
        pushEvent('call.auto_answer_triggered', `caller=${CALLER.name} · answered from barge-in during the mock run`, {
          mode: 'barge',
          since_event: 'barge_in.intent_classified',
          delta_ms: deltaSince('call.auto_answer_triggered') ?? 0,
        })
        connectedEventRef.current = true
        pushEvent('call.connected', 'barge-answered — you are live with the scripted caller', { mode: 'barge' })
      } else {
        skipCurrentMockLine()
      }
      // Answered by voice before the 30 s ring — skip the opening "network
      // connected us" line (the connection was not automatic).
      if (!mockRef.current.started) mockRef.current.idx = 1
      setCallStateLabel('CONNECTED')
      if (liveNowRef.current) liveNowRef.current({ from: 'barge' })
      return
    }
    // DISMISS_RECAP — stop only. If the call already auto-connected we go live;
    // otherwise we keep ringing and the network pickup connects it at ~30 s.
    if (pickedUpRef.current) {
      skipCurrentMockLine()
      if (liveNowRef.current) liveNowRef.current({ from: 'dismiss' })
    }
  }

  // Presenter voice while the mock-caller option is active. Echoes of the
  // scripted caller line (speaker output leaking into the mic) are dropped;
  // recognised commands stop the recap; everything else is just the presenter's
  // turn and is recorded once the call is connected.
  const handleAutoSpeech = useCallback(
    async (rawText) => {
      const text = (rawText || '').trim()
      if (!aliveRef.current || !text) return
      const now = performance.now()
      const m = mockRef.current
      m.recent = m.recent.filter((r) => now <= r.untilMs)
      if (m.recent.some((r) => isEchoOf(r.text, text))) {
        setInterimText('')
        pushEvent('caller.echo_filtered', `dropped mic echo of scripted Z: “${text}”`, { raw: text })
        return
      }
      setInterimText('')
      const s = sessionRef.current
      const recapPlaying = Boolean(s.audioEl) && !s.audioEl.paused && !s.audioEl.ended
      if (recapPlaying) {
        let intent = null
        try {
          intent = (await api.classifyIntent(text)).intent || null
        } catch {
          intent = null
        }
        if (intent === 'ANSWER_CALL' || intent === 'DISMISS_RECAP') {
          await stopRecapForBarge(text, intent)
          return
        }
        // Plain speech while the recap plays → the recap keeps going; the turn
        // is only recorded once the presenter is actually connected.
      }
      if (pickedUpRef.current) await commitTurn('USER', text, SESSIONS.call2)
    },
    [commitTurn, pushEvent],
  )
  handleAutoSpeechRef.current = handleAutoSpeech
  doPickupRef.current = doPickup
  liveNowRef.current = liveNow

  // ── Second call / wrap-up ───────────────────────────────────────────────────
  const advanceToConnected = useCallback(async () => {
    if (!aliveRef.current) return
    scriptCancelRef.current = false
    stopMic()
    stopRingback()
    teardownRecapAudio()
    setCallStateLabel('CONNECTED')
    setRecapState(null)
    setPhase(PHASE.CONNECTED)
    pushEvent('call.connected', 'caller=Z · live again — you are already caught up')
  }, [pushEvent, stopMic, teardownRecapAudio])
  const advanceToConnectedRef = useRef(null)
  advanceToConnectedRef.current = advanceToConnected

  const answerCall = useCallback(async () => {
    if (!aliveRef.current || phase !== PHASE.RECAP) return
    if (chosenModeRef.current === 'autoPickup') {
      // Mock run — answering sends the presenter straight into the live stage
      // with the scripted caller (auto-captured turns on both sides).
      stopRingback()
      if (!pickedUpRef.current) {
        pickedUpRef.current = true
        clearPickupTimer()
        connectedEventRef.current = true
        pushEvent('call.connected', 'caller=Z · answered manually — mock run continues live', { mode: 'manual' })
        // Answered before the ring window ended — skip the "network connected
        // us" opening line of the script.
        if (!mockRef.current.started) mockRef.current.idx = 1
      }
      setCallStateLabel('CONNECTED')
      if (liveNowRef.current) liveNowRef.current({ from: 'manual' })
      return
    }
    stopMic()
    stopRingback()
    await advanceToConnected()
  }, [advanceToConnected, phase, stopMic, pushEvent])

  const endCall = useCallback(async () => {
    if (!aliveRef.current) return
    scriptCancelRef.current = true
    stopMic()
    stopMockCaller()
    clearPickupTimer()
    teardownRecapAudio()
    setPhase(PHASE.COMPLETED)
    setCallStateLabel('COMPLETED')
    pushEvent('call.completed', 'second call ended normally')
    try {
      await api.endCallOne({
        sessionId: SESSIONS.call2,
        callerId: CALLER.callerId,
        callerName: CALLER.name,
        interrupted: false,
      })
    } catch {
      /* best-effort */
    }
    const log = eventsRef.current
    const findEvent = (name) => log.find((e) => e.name === name)
    const matchEvent = findEvent('thread.match_found')
    const firstAudio = findEvent('recap.tts_first_audio')
    const halted = findEvent('tts.playback_halted')
    const detected = findEvent('barge_in.detected')
    const autoAnswer = findEvent('call.auto_answer_triggered')
    const changed = log.find((e) => e.name === 'freshness.discrepancy_found')
    let answerToConnectMs = null
    if (autoAnswer) {
      const connectedAfter = log.find((e) => e.name === 'call.connected' && e.epoch >= autoAnswer.epoch)
      answerToConnectMs = connectedAfter ? Math.max(0, connectedAfter.epoch - autoAnswer.epoch) : null
    }
    setMetrics({
      recapLatencyMs: firstAudio && matchEvent ? Math.max(0, firstAudio.epoch - matchEvent.epoch) : null,
      bargeHaltMs: halted ? (halted.meta.delta_ms ?? (detected ? halted.epoch - detected.epoch : null)) : null,
      freshnessChanged: Boolean(changed && !String(changed.meta.status || '').startsWith('UNAVAIL')),
      freshnessDetail: changed ? changed.detail : null,
      autoAnswered: Boolean(autoAnswer),
      autoPickupMode: autoAnswer?.meta?.mode || null, // 'network' | 'barge'
      answerToConnectMs,
      mockLines: log.filter((e) => e.name === 'caller.mock_line').length,
      echoFiltered: log.filter((e) => e.name === 'caller.echo_filtered').length,
      intent: bargeResult ? bargeResult.action : null,
      bargePhrase: bargeResult ? bargeResult.phrase : null,
      turns: call1Turns.length + call2Turns.length,
    })
  }, [bargeResult, call1Turns.length, call2Turns.length, pushEvent, stopMic, teardownRecapAudio])

  const fullReset = useCallback(async () => {
    clearAll()
    try {
      await api.resetDemo({ callerId: CALLER.callerId, sessionIds: [SESSIONS.call1, SESSIONS.call2] })
    } catch {
      /* offline reset is fine */
    }
  }, [clearAll])

  // ── bootstrap ───────────────────────────────────────────────────────────────
  const loadCapabilities = useCallback(async () => {
    setCapsState('loading')
    try {
      const data = await api.getCapabilities()
      setCaps(data)
      setCapsState('ready')
      setCapsError(null)
      if (data && !data.ready) setPhase(PHASE.IDLE)
    } catch (err) {
      setCapsState('error')
      setCapsError(err.message || 'Dashboard server unreachable')
      setPhase(PHASE.IDLE)
    }
  }, [])

  useEffect(() => {
    loadCapabilities()
    return () => {
      aliveRef.current = false
      stopRingback()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return {
    caps,
    capsState,
    capsError,
    phase,
    recapState,
    callStateLabel,
    events,
    call1Turns,
    call2Turns,
    threadSummary,
    recap,
    spokenIdx,
    audioStatus,
    listening,
    micError,
    interimText,
    bargeResult,
    chosenMode,
    memoryBusy,
    recordingSpeaker,
    metrics,
    error,
    retryCaps: loadCapabilities,
    lang,
    chosenScenario,
    selectScenario,
    startCall1,
    startTurn,
    endTurn,
    simulateDrop,
    continueToCallback,
    chooseRecapMode,
    resumeRecapPlayback: async () => {
      if (resumeRef.current) await resumeRef.current()
    },
    armBargeMic,
    replayRecap,
    testPhrase,
    answerCall,
    endCall,
    fullReset,
    stopMic,
    pickupCountdownS,
    mockLineSpoken,
    mockError,
  }
}