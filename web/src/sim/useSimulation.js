import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api.js'
import {
  CALL1_USER_SUGGESTIONS,
  CALL1_Z_LINES,
  CALL2_USER_SUGGESTIONS,
  CALL2_Z_LINES,
  CALLER,
  CLOCK,
  EVENT_KINDS,
  INTENT_LABELS,
  PRIVATE_TRACK_ID,
  SESSIONS,
} from './config.js'
import {
  speakCallerLine,
  startRingback,
  stopCallerSpeech,
  stopRingback,
} from './callerVoice.js'
import { micStreamSupported, startMicStream } from './userMic.js'

export const PHASE = {
  BOOT: 'boot', // probing the backend
  IDLE: 'idle', // ready to start / setup help shown
  CALL1: 'call1', // yesterday's live conversation with Z
  MEMORY: 'memory', // interrupted thread persisted, before the callback
  RECAP: 'recap', // next-morning callback: RINGING + private recap
  CONNECTED: 'connected', // second call live (after recap / barge-in)
  COMPLETED: 'completed', // evidence panel
}

export const RECAP_STATE = {
  READY: 'ready', // recap text ready, awaiting an option
  LOADING: 'loading', // Rime synthesizing
  PLAYING: 'playing',
  HALTED: 'halted', // barge-in stopped the whisper
  DONE: 'done', // recap finished naturally
  ERROR: 'error', // Rime unreachable (no fallback audio)
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
  const [chosenMode, setChosenMode] = useState(null) // 'full' | 'barge'
  const [memoryBusy, setMemoryBusy] = useState(false)
  const [activeSpeaker, setActiveSpeaker] = useState(null) // 'caller' when Z speaks
  const [metrics, setMetrics] = useState(null)
  const [error, setError] = useState(null)

  // ── mutable session plumbing ────────────────────────────────────────────────
  const aliveRef = useRef(true)
  const sessionRef = useRef({ mic: null, audioEl: null, audioUrl: null, listeningFor: null })
  const clockRef = useRef({ anchor: new Date(), perf: performance.now() })
  const anchorsRef = useRef({})
  const eventsRef = useRef([])
  const waitersRef = useRef([]) // resolvers waiting for the user's spoken/typed reply
  const handledBargeRef = useRef(false)
  const bargeArmedRef = useRef(false)
  const scriptCancelRef = useRef(false)
  const sessionKeyRef = useRef(0) // bumped to invalidate in-flight script loops

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
    stopCallerSpeech()
    stopRingback()
    stopMicSafe()
    teardownRecapAudio()
    eventsRef.current = []
    waitersRef.current = []
    anchorsRef.current = {}
    handledBargeRef.current = false
    bargeArmedRef.current = false
    scriptCancelRef.current = true
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
    setMemoryBusy(false)
    setMetrics(null)
    setError(null)
    setInterimText('')
    setListening(false)
    setActiveSpeaker(null)
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
    setListening(false)
    setInterimText('')
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
    setListening(false)
    setInterimText('')
  }, [])

  // ── transcript plumbing ─────────────────────────────────────────────────────
  const resolveWaiters = useCallback((text) => {
    if (waitersRef.current.length) {
      const resolve = waitersRef.current.shift()
      resolve(text)
      return true
    }
    return false
  }, [])

  // Waits for the presenter's next spoken or typed reply.
  const waitForUserReply = useCallback((timeoutMs) => {
    return Promise.race([
      new Promise((resolve) => waitersRef.current.push(resolve)),
      wait(timeoutMs).then(() => null),
    ])
  }, [])

  const recordAndForwardUserTurn = useCallback(
    async (text, sessionId) => {
      const cleaned = (text || '').trim()
      if (!cleaned) return
      try {
        await api.recordTurn({ sessionId, speaker: 'USER', text: cleaned })
      } catch {
        /* memory is best-effort during the live call */
      }
      resolveWaiters(cleaned)
    },
    [resolveWaiters],
  )

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
            if (sessionRef.current.listeningFor === 'barge' && handleBargeRef.current) {
              handleBargeRef.current(m.text)
            } else {
              recordAndForwardUserTurn(m.text, sessionId)
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
    [caps, recordAndForwardUserTurn, stopMic],
  )

  // ── Z (simulated caller) line runner ────────────────────────────────────────
  const runCallerScript = useCallback(
    async (lines, { sessionId, turnSetter, endHint }) => {
      scriptCancelRef.current = false
      for (const line of lines) {
        if (!aliveRef.current || scriptCancelRef.current) return 'done'
        setActiveSpeaker('caller')
        turnSetter((prev) => [...prev, { id: uid(), speaker: 'CALLER', text: line.text, live: true }])
        try {
          await api.recordTurn({ sessionId, speaker: 'CALLER', text: line.text })
        } catch {
          /* best-effort */
        }
        if (endHint) endHint(line.hint)

        let speakResult
        if (line.cut) {
          // Drop the call mid-sentence: cut the voice and finish this script.
          speakResult = await Promise.race([
            speakCallerLine(line.text),
            wait(2400).then(() => {
              stopCallerSpeech()
              return 'cut'
            }),
          ])
        } else {
          await speakCallerLine(line.text)
          speakResult = 'done'
        }
        setActiveSpeaker(null)
        if (!aliveRef.current || scriptCancelRef.current) return 'done'
        turnSetter((prev) => prev.map((t, i) => (i === prev.length - 1 ? { ...t, live: false } : t)))
        if (speakResult === 'cut') return 'cut'

        // Pause for the presenter's reply before Z continues.
        await waitForUserReply(line.waitMs || 9000)
        if (!aliveRef.current || scriptCancelRef.current) return 'done'
      }
      return 'done'
    },
    [waitForUserReply],
  )

  // ── Call one (yesterday) ────────────────────────────────────────────────────
  const simulateDropRef = useRef(null)
  const simulateDrop = useCallback(async () => {
    if (!aliveRef.current) return
    scriptCancelRef.current = true
    stopMic()
    stopCallerSpeech()
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
    pushEvent('call.connected', 'caller=Z · session call-1 · normal call begins')
    if (caps && caps.stt && caps.stt.enabled) {
      await startMic('convo', SESSIONS.call1)
    } else {
      setMicError('Typed replies mode — click a suggested line under the transcript to speak as "You".')
    }
    const outcome = await runCallerScript(CALL1_Z_LINES, {
      sessionId: SESSIONS.call1,
      turnSetter: setCall1Turns,
      endHint: () => {},
    })
    if (outcome === 'cut' && aliveRef.current) simulateDropRef.current?.()
  }, [caps, pushEvent, remember, runCallerScript, setClock, startMic])

  // Typed / suggested "You" line — the deterministic fallback for the mic path.
  const suggestReply = useCallback(
    (text, listKey) => {
      if (!aliveRef.current || !text.trim()) return
      const sessionId = listKey === 'call2' ? SESSIONS.call2 : SESSIONS.call1
      const turnSetter = listKey === 'call2' ? setCall2Turns : setCall1Turns
      turnSetter((prev) => [...prev, { id: uid(), speaker: 'USER', text, live: false }])
      api.recordTurn({ sessionId, speaker: 'USER', text }).catch(() => {})
      resolveWaiters(text)
    },
    [resolveWaiters],
  )

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
        ringWindowS: 25,
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
    try {
      const { objectUrl, fetchMs } = await api.fetchRimeAudio(current.text, {
        trackId: PRIVATE_TRACK_ID,
        speaker: current.speaker,
        model: current.model,
      })
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
        setAudioStatus('idle')
        setSpokenIdx(Math.max(0, sentences.length - 1))
        // A finished recap no longer needs the barge-in mic.
        if (sessionRef.current.listeningFor === 'barge') stopMic()
      }
      await audio.play()
      if (aliveRef.current) {
        setAudioStatus('playing')
        setRecapState(RECAP_STATE.PLAYING)
        pushEvent('recap.tts_first_audio', `Δ ${deltaSince('match') ?? '?'}ms from match`, { since_event: 'thread.match_found', delta_ms: deltaSince('match') ?? null, rime_fetch_ms: Math.round(fetchMs) })
      }
    } catch (err) {
      if (aliveRef.current) {
        setAudioStatus('error')
        setRecapState(RECAP_STATE.ERROR)
        setError(`Rime did not return audio: ${err.message}`)
      }
    }
  }, [recap, teardownRecapAudio, pushEvent, deltaSince, stopMic])

  const chooseRecapMode = useCallback(
    async (mode) => {
      setChosenMode(mode)
      handledBargeRef.current = false
      bargeArmedRef.current = mode === 'barge'
      setBargeResult(null)
      setError(null)
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

  // Turn full-duplex listening on/off mid-recap without re-playing audio.
  const armBargeMic = useCallback(async () => {
    if (!aliveRef.current) return
    bargeArmedRef.current = true
    setChosenMode('barge')
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
      await handleBargeUtterance(text)
    },
    [handleBargeUtterance, phase],
  )

  // ── Second call / wrap-up ───────────────────────────────────────────────────
  const advanceToConnected = useCallback(async () => {
    if (!aliveRef.current) return
    scriptCancelRef.current = false
    stopMic()
    stopRingback()
    stopCallerSpeech()
    teardownRecapAudio()
    setCallStateLabel('CONNECTED')
    setRecapState(null)
    setPhase(PHASE.CONNECTED)
    pushEvent('call.connected', 'caller=Z · live again — you are already caught up')
    if (caps && caps.stt && caps.stt.enabled) {
      await startMic('convo', SESSIONS.call2)
    }
    const outcome = await runCallerScript(CALL2_Z_LINES, {
      sessionId: SESSIONS.call2,
      turnSetter: setCall2Turns,
      endHint: () => {},
    })
    if (outcome === 'done' && aliveRef.current) {
      // Presenter ends the call when ready.
    }
  }, [caps, pushEvent, runCallerScript, startMic, stopMic, teardownRecapAudio])
  const advanceToConnectedRef = useRef(null)
  advanceToConnectedRef.current = advanceToConnected

  const answerCall = useCallback(async () => {
    if (!aliveRef.current || phase !== PHASE.RECAP) return
    stopMic()
    stopRingback()
    await advanceToConnected()
  }, [advanceToConnected, phase, stopMic])

  const endCall = useCallback(async () => {
    if (!aliveRef.current) return
    scriptCancelRef.current = true
    stopMic()
    stopCallerSpeech()
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
    const connected = log.find((e) => e.name === 'call.connected' && e.detail.includes('caught up'))
    setMetrics({
      recapLatencyMs: firstAudio && matchEvent ? Math.max(0, firstAudio.epoch - matchEvent.epoch) : null,
      bargeHaltMs: halted ? (halted.meta.delta_ms ?? (detected ? halted.epoch - detected.epoch : null)) : null,
      freshnessChanged: Boolean(changed && !String(changed.meta.status || '').startsWith('UNAVAIL')),
      freshnessDetail: changed ? changed.detail : null,
      autoAnswered: Boolean(autoAnswer),
      answerToConnectMs: autoAnswer && connected ? Math.max(0, connected.epoch - autoAnswer.epoch) : null,
      intent: bargeResult ? bargeResult.action : null,
      bargePhrase: bargeResult ? bargeResult.phrase : null,
    })
  }, [bargeResult, pushEvent, stopMic])

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
      stopCallerSpeech()
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
    activeSpeaker,
    metrics,
    error,
    capsSuggestions: { call1: CALL1_USER_SUGGESTIONS, call2: CALL2_USER_SUGGESTIONS },
    retryCaps: loadCapabilities,
    startCall1,
    suggestReply,
    simulateDrop,
    continueToCallback,
    chooseRecapMode,
    armBargeMic,
    replayRecap,
    testPhrase,
    answerCall,
    endCall,
    fullReset,
    stopMic,
  }
}
