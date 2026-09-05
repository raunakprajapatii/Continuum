// Thin client for the Continuum control-surface endpoints the demo uses.
// All requests go through the Vite dev proxy to the FastAPI dashboard server.

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body && body.detail) detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail)
  }
  return response
}

export function capsEndpoint() {
  return '/api/capabilities'
}

export async function getCapabilities() {
  const response = await request(capsEndpoint())
  return response.json()
}

export async function resetDemo({ callerId, sessionIds }) {
  await request('/api/sim/reset', {
    method: 'POST',
    body: JSON.stringify({ caller_id: callerId, session_ids: sessionIds }),
  })
}

export async function recordTurn({ sessionId, speaker, text }) {
  await request('/api/sim/turn', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, speaker, text }),
  })
}

export async function endCallOne({ sessionId, callerId, callerName, interrupted }) {
  const response = await request('/api/sim/call-ended', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      caller_id: callerId,
      caller_name: callerName,
      interrupted,
    }),
  })
  return response.json()
}

export async function buildRecap({ callerId, sessionId, ringWindowS, language }) {
  const response = await request('/api/sim/recap', {
    method: 'POST',
    body: JSON.stringify({
      caller_id: callerId,
      session_id: sessionId,
      ring_window_s: ringWindowS,
      language,
    }),
  })
  return response.json()
}

export async function classifyIntent(text) {
  const response = await request('/api/sim/barge-intent', {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
  return response.json()
}

/**
 * Synthesize recap text via Rime and return a playable object URL.
 *
 * The response MUST carry the private-track header — this mirrors the
 * dashboard's fence: recap audio is bound to the user's whisper track only.
 */
export async function fetchRimeAudio(text, { trackId, speaker, model, timeScaleFactor, lang } = {}) {
  const started = performance.now()
  const response = await request('/api/rime/tts', {
    method: 'POST',
    body: JSON.stringify({ text, speaker, model, time_scale_factor: timeScaleFactor, lang }),
  })
  const track = response.headers.get('X-Continuum-Track')
  if (trackId && track !== trackId) {
    throw new ApiError(500, `Recap audio not bound to private track (got "${track}")`)
  }
  const objectUrl = URL.createObjectURL(await response.blob())
  return { objectUrl, track, fetchMs: performance.now() - started }
}
