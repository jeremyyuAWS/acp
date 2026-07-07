// Phase 2 — detect-and-route media/target checks (1.2.1, 1.2.2, 1.2.3, 2.5.8).
// These have no deterministic fix (captions/transcripts need the audio; resizing
// is layout-sensitive), so the contract is: check() flags the bad case, passes
// the well-formed case, and the module is fixMode 'human-only' so findings route
// to HITL instead of being auto-passed.
import { describe, it, expect } from 'vitest'
import * as r121 from './wcag-1-2-1.js'
import * as r122 from './wcag-1-2-2.js'
import * as r123 from './wcag-1-2-3.js'
import * as r258 from './wcag-2-5-8.js'
import { allRules, PLAIN_NAMES, runFixes, runChecks } from './index.js'

const parse = (body) =>
  new DOMParser().parseFromString(
    `<!doctype html><html><body>${body}</body></html>`,
    'text/html'
  )

describe('registration', () => {
  it('all Phase 2 modules are registered, human-only, with plain names', () => {
    const byId = Object.fromEntries(allRules.map((r) => [r.meta.id, r.meta]))
    for (const sc of ['1.2.1', '1.2.2', '1.2.3', '2.5.8']) {
      expect(byId[sc], `${sc} not registered`).toBeTruthy()
      expect(byId[sc].fixMode).toBe('human-only')
      expect(PLAIN_NAMES[sc]).toBeTruthy()
    }
  })

  it('human-only findings are detected but never auto-fixed', () => {
    const doc = parse(`<video></video>`)
    // runChecks surfaces the FAIL...
    const checked = runChecks(doc, { aiEnabled: true })
    expect(checked.some((c) => c.rule.id === '1.2.2' && c.outcome === 'FAIL')).toBe(true)
    // ...but runFixes never touches it (no auto-pass) — the markup is unchanged.
    const before = doc.body.innerHTML
    runFixes(doc, { aiEnabled: true })
    expect(doc.body.innerHTML).toBe(before)
  })
})

describe('1.2.2 Captions', () => {
  it('flags a video with no captions track', () => {
    expect(r122.check(parse(`<video src="v.mp4"></video>`))).toHaveLength(1)
    expect(r122.check(parse(`<video><track kind="descriptions"></video>`))).toHaveLength(1)
  })
  it('passes a video with a captions or subtitles track', () => {
    expect(r122.check(parse(`<video><track kind="captions" src="c.vtt"></video>`))).toEqual([])
    expect(r122.check(parse(`<video><track kind="subtitles" src="s.vtt"></video>`))).toEqual([])
  })
})

describe('1.2.3 Audio Description', () => {
  it('flags a video with no description track and no transcript', () => {
    expect(r123.check(parse(`<video><track kind="captions"></video>`))).toHaveLength(1)
  })
  it('passes with a descriptions track or a linked transcript', () => {
    expect(r123.check(parse(`<video><track kind="descriptions"></video>`))).toEqual([])
    expect(r123.check(parse(`<video aria-describedby="t"></video><p id="t">…</p>`))).toEqual([])
  })
})

describe('1.2.1 Audio-only', () => {
  it('flags an audio element with no transcript', () => {
    expect(r121.check(parse(`<audio src="a.mp3"></audio>`))).toHaveLength(1)
  })
  it('passes audio with a linked/naming transcript; ignores video', () => {
    expect(r121.check(parse(`<audio aria-describedby="t"></audio><p id="t">…</p>`))).toEqual([])
    expect(r121.check(parse(`<audio aria-label="Podcast transcript below"></audio>`))).toEqual([])
    expect(r121.check(parse(`<video></video>`))).toEqual([])
  })
})

describe('2.5.8 Target Size', () => {
  it('flags an interactive target with an inline dimension under 24px', () => {
    expect(r258.check(parse(`<button style="width:16px;height:16px">x</button>`))).toHaveLength(1)
    expect(r258.check(parse(`<a href="#" style="height:12px">x</a>`))).toHaveLength(1)
  })
  it('passes targets ≥24px, non-px units, or no inline size; ignores non-interactive', () => {
    expect(r258.check(parse(`<button style="width:48px;height:48px">x</button>`))).toEqual([])
    expect(r258.check(parse(`<button style="width:100%">x</button>`))).toEqual([])
    expect(r258.check(parse(`<button>x</button>`))).toEqual([])
    expect(r258.check(parse(`<span style="width:10px;height:10px">x</span>`))).toEqual([])
  })
})
