// Screen-reader audio preview — hear a fix the way a blind user would (local, private TTS).
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { srPhrase, srSupported, speakAsScreenReader, stopSpeaking } from './srPreview.js'

describe('srPhrase — screen-reader framing per criterion', () => {
  it('prepends the role a screen reader announces', () => {
    expect(srPhrase('1.1.1', 'a nurse reviewing a chart')).toBe('Image. a nurse reviewing a chart')
    expect(srPhrase('2.4.6', 'Quarterly results')).toBe('Heading. Quarterly results')
    expect(srPhrase('2.4.4', 'Download the report')).toBe('Link. Download the report')
    expect(srPhrase('2.4.2', 'Benefits guide')).toBe('Document title. Benefits guide')
  })
  it('reads an unmapped criterion verbatim', () => {
    expect(srPhrase('3.1.5', 'plain language')).toBe('plain language')
  })
  it('returns empty for a blank value (nothing to play)', () => {
    expect(srPhrase('1.1.1', '   ')).toBe('')
    expect(srPhrase('1.1.1', null)).toBe('')
  })
})

describe('speakAsScreenReader — uses the local Web Speech API', () => {
  beforeEach(() => {
    const spoken = []
    global.window = {
      speechSynthesis: { speak: (u) => { spoken.push(u); u.onstart && u.onstart(); u.onend && u.onend() }, cancel: vi.fn() },
      SpeechSynthesisUtterance: class { constructor(t) { this.text = t } },
    }
    global.window._spoken = spoken
  })

  it('speaks the screen-reader-framed text and fires callbacks', () => {
    const onStart = vi.fn(); const onEnd = vi.fn()
    const ok = speakAsScreenReader('1.1.1', 'a chart', { onStart, onEnd })
    expect(ok).toBe(true)
    expect(global.window._spoken[0].text).toBe('Image. a chart')
    expect(onStart).toHaveBeenCalled()
    expect(onEnd).toHaveBeenCalled()
  })

  it('cancels any in-flight speech before starting (one preview at a time)', () => {
    speakAsScreenReader('1.1.1', 'first')
    expect(global.window.speechSynthesis.cancel).toHaveBeenCalled()
  })

  it('is a no-op for a blank value', () => {
    expect(speakAsScreenReader('1.1.1', '')).toBe(false)
  })

  it('degrades gracefully when the browser has no speech synthesis', () => {
    global.window = {}
    expect(srSupported()).toBe(false)
    expect(speakAsScreenReader('1.1.1', 'x')).toBe(false)
    expect(() => stopSpeaking()).not.toThrow()
  })
})
