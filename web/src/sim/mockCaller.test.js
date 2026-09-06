import { beforeEach, describe, expect, it, vi } from 'vitest'
import { normalizeText, isEchoOf, preloadMockLines } from './mockCaller.js'
import * as api from './api.js'

vi.mock('./api.js', () => ({
  fetchRimeAudio: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('normalizeText', () => {
  it('lowercases, strips punctuation and collapses whitespace', () => {
    expect(normalizeText('Hey, how ARE you?!')).toBe('hey how are you')
    expect(normalizeText('  Basmati  rice 1121,  $940/t  ')).toBe('basmati rice 1121 940 t')
  })

  it('keeps apostrophes so contractions survive', () => {
    expect(normalizeText("didn't stop")).toBe("didn't stop")
  })

  it('handles empty and non-string input', () => {
    expect(normalizeText('')).toBe('')
    expect(normalizeText('   ')).toBe('')
    expect(normalizeText(null)).toBe('')
    expect(normalizeText(undefined)).toBe('')
  })
})

describe('isEchoOf', () => {
  it('returns true for identical text modulo case and punctuation', () => {
    expect(isEchoOf('Can you hear me?', 'can you hear me')).toBe(true)
  })

  it('detects a short definite substring echo', () => {
    const known = 'So, did you get a chance to check the Basmati rice 1121 quote? Export grade is at $940 per tonne.'
    expect(isEchoOf(known, 'the Basmati rice 1121 quote')).toBe(true)
  })

  it('detects a high token-overlap paraphrase of a played line', () => {
    const known = 'So, did you get a chance to check the Basmati rice 1121 quote?'
    const heard = 'did you get a chance to check the basmati rice 1121 quote'
    expect(isEchoOf(known, heard)).toBe(true)
  })

  it('rejects unrelated speech', () => {
    expect(isEchoOf('the copper cathode holds at 8940', 'good morning how are you today')).toBe(false)
  })

  it('rejects too-short matches below the minChars floor', () => {
    expect(isEchoOf('hold on one second', 'on')).toBe(false)
  })

  it('respects a custom minOverlap', () => {
    expect(isEchoOf('a b c d', 'a b x y')).toBe(false)
    expect(isEchoOf('a b c d', 'a b x y', { minOverlap: 0.4 })).toBe(true)
  })

  it('returns false for empty input', () => {
    expect(isEchoOf('', 'hello')).toBe(false)
    expect(isEchoOf('hello', '')).toBe(false)
  })
})

describe('preloadMockLines', () => {
  it('synthesizes every line, sorted by index, with a default gapMs of 0', async () => {
    api.fetchRimeAudio.mockResolvedValue({ objectUrl: 'blob:x', track: 'continuum-private-whisper' })
    const lines = [
      { text: 'First line', gapMs: 500 },
      { text: 'Second line' },
      { text: 'Third line' },
    ]
    const prepared = await preloadMockLines(lines, {
      speaker: 'cupola',
      model: 'coda',
      timeScaleFactor: 1,
      lang: 'en',
    })
    expect(prepared).toEqual([
      { index: 0, text: 'First line', gapMs: 500, objectUrl: 'blob:x' },
      { index: 1, text: 'Second line', gapMs: 0, objectUrl: 'blob:x' },
      { index: 2, text: 'Third line', gapMs: 0, objectUrl: 'blob:x' },
    ])
    expect(api.fetchRimeAudio).toHaveBeenCalledWith('First line', {
      speaker: 'cupola',
      model: 'coda',
      timeScaleFactor: 1,
      lang: 'en',
    })
  })

  it('skips lines that fail to synthesize instead of dropping the whole script', async () => {
    api.fetchRimeAudio
      .mockResolvedValueOnce({ objectUrl: 'blob:ok-0' })
      .mockRejectedValueOnce(new Error('Rime 503'))
      .mockResolvedValueOnce({ objectUrl: 'blob:ok-2' })
    const prepared = await preloadMockLines([{ text: 'a' }, { text: 'b' }, { text: 'c' }])
    expect(prepared).toEqual([
      { index: 0, text: 'a', gapMs: 0, objectUrl: 'blob:ok-0' },
      { index: 2, text: 'c', gapMs: 0, objectUrl: 'blob:ok-2' },
    ])
  })

  it('returns an empty list when every line fails', async () => {
    api.fetchRimeAudio.mockRejectedValue(new Error('Rime unavailable'))
    const prepared = await preloadMockLines([{ text: 'a' }, { text: 'b' }])
    expect(prepared).toEqual([])
  })
})