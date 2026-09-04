// Browser mic -> backend WebSocket -> Deepgram streaming STT.
//
// Captures mono audio, resamples it to 16 kHz PCM16 and streams the bytes to
// the dashboard's /api/stt/stream socket. Transcript messages come back as
// JSON { type: "transcript", speaker: "USER", text, is_final }.

const TARGET_RATE = 16000

function buildWebSocketUrl(sessionId) {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/api/stt/stream?session_id=${encodeURIComponent(sessionId)}`
}

export function micStreamSupported() {
  return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.AudioContext)
}

/**
 * Start capturing the user's microphone and streaming it to Deepgram.
 *
 * @param {{ sessionId: string, onTranscript: (m: {text,isFinal,confidence}) => void,
 *           onError: (e: {code,message}) => void, onReady: () => void }} opts
 * @returns {Promise<{ stop: () => void }>}
 */
export async function startMicStream({ sessionId, onTranscript, onError, onReady }) {
  if (!micStreamSupported()) {
    throw new Error('Microphone capture is not supported in this browser')
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  })

  const Ctx = window.AudioContext || window.webkitAudioContext
  const audioContext = new Ctx()
  const source = audioContext.createMediaStreamSource(stream)

  const ws = new WebSocket(buildWebSocketUrl(sessionId))
  let canSend = false
  let closed = false

  const sendError = (code, message) => {
    if (!closed && onError) onError({ code, message })
  }

  const processor = audioContext.createScriptProcessor(4096, 1, 1)
  const sampleRate = audioContext.sampleRate

  processor.onaudioprocess = (event) => {
    if (!canSend || closed || ws.readyState !== WebSocket.OPEN) return
    const input = event.inputBuffer.getChannelData(0)
    const outLength = Math.max(1, Math.round((input.length * TARGET_RATE) / sampleRate))
    const buffer = new ArrayBuffer(outLength * 2)
    const view = new Int16Array(buffer)
    const ratio = input.length / outLength
    for (let i = 0; i < outLength; i += 1) {
      const sample = input[Math.min(input.length - 1, Math.floor(i * ratio))] || 0
      const clamped = Math.max(-1, Math.min(1, sample))
      view[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
    }
    ws.send(buffer)
  }

  ws.onmessage = (event) => {
    let message
    try {
      message = JSON.parse(event.data)
    } catch {
      return
    }
    if (message.type === 'ready') {
      canSend = true
      if (onReady) onReady()
    } else if (message.type === 'transcript') {
      if (onTranscript) {
        onTranscript({
          text: message.text,
          isFinal: Boolean(message.is_final),
          confidence: message.confidence,
        })
      }
    } else if (message.type === 'error') {
      sendError(message.code, message.message)
    }
  }

  ws.onerror = () => sendError('stt_connection', 'Speech-to-text connection failed')
  ws.onclose = () => {
    canSend = false
  }

  source.connect(processor)
  processor.connect(audioContext.destination)

  return {
    stop() {
      closed = true
      canSend = false
      try {
        ws.close()
      } catch {
        /* noop */
      }
      try {
        processor.disconnect()
        source.disconnect()
      } catch {
        /* noop */
      }
      stream.getTracks().forEach((track) => track.stop())
      audioContext.close().catch(() => {})
    },
  }
}
