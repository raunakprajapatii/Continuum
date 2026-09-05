// Scripted mock-caller helpers for the auto-pickup (India ring) option.
//
// In that option a hard-coded "Z" line set is spoken on the caller lane while
// the recap whisper is still playing. The lines are *authored text* — they are
// recorded straight to thread memory as CALLER turns and never need to come
// back through the presenter's microphone. Because the caller-lane audio
// inevitably bleeds into the browser mic at demo volume, these helpers also
// let the hook drop any STT final that merely echoes a line that just played,
// so the mock caller's voice is never "taken as input".
import * as api from './api.js'

/** Lowercase + strip punctuation so two transcriptions can be compared. */
export function normalizeText(value) {
  return (value || '')
    .toLowerCase()
    .replace(/[^a-z0-9\s']/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function tokensOf(text) {
  const normalized = normalizeText(text)
  return normalized ? normalized.split(' ') : []
}

/**
 * True when `heard` (an STT final caught by the presenter's mic) is really the
 * mock-caller line `known` playing back through the speakers.
 */
export function isEchoOf(known, heard, { minOverlap = 0.55, minChars = 5 } = {}) {
  const knownNorm = normalizeText(known)
  const heardNorm = normalizeText(heard)
  if (!knownNorm || !heardNorm) return false
  if (knownNorm === heardNorm) return true

  // A short definite substring is a strong echo signal ("can you hear me?").
  if (heardNorm.length >= minChars && (knownNorm.includes(heardNorm) || heardNorm.includes(knownNorm))) {
    return true
  }

  // Otherwise compare token overlap between the two utterances.
  const knownTokens = tokensOf(known)
  const heardTokens = tokensOf(heard)
  if (!knownTokens.length || !heardTokens.length) return false
  const smaller = knownTokens.length <= heardTokens.length ? knownTokens : heardTokens
  const larger = knownTokens.length <= heardTokens.length ? heardTokens : knownTokens
  const smallerSet = new Set(smaller)
  let hits = 0
  for (const word of larger) {
    if (smallerSet.has(word)) hits += 1
  }
  return hits / larger.length >= minOverlap
}

/**
 * Synthesize every scripted mock-caller line with Rime (separate caller voice,
 * natural pace) and return objects the hook can queue as audio elements.
 *
 * Synthesis is resilient: a single line that fails (Rime unavailable, key
 * missing, voice declined) is skipped instead of silencing the whole script,
 * so the mock caller still speaks the lines that did prepare.
 */
export async function preloadMockLines(lines, { speaker, model, timeScaleFactor, lang } = {}) {
  const prepared = []
  await Promise.all(
    lines.map(async (line, index) => {
      try {
        const { objectUrl } = await api.fetchRimeAudio(line.text, {
          speaker,
          model,
          timeScaleFactor,
          lang,
        })
        prepared.push({ index, text: line.text, gapMs: line.gapMs ?? 0, objectUrl })
      } catch {
        // Skip this line — the remaining script still plays.
      }
    }),
  )
  return prepared.sort((a, b) => a.index - b.index)
}
