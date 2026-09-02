// The synchronised caption editor, RENDERED — not read from source.
//
// The other caption tests in this repo assert on source text, because what they pin is a decision
// expressed as an expression (`editable = !explainOnly && …`). What this file pins is behaviour a
// reviewer performs: play, see the line under the playhead, click to seek, correct a word, and
// have the correction land in the value that gets approved. None of that is legible in a regex.
//
// jsdom does not implement media playback — `play()` is absent and `currentTime` is a plain
// property — which is exactly right here: what is under test is the component's own reaction to
// time changing, so the time is set directly and the `timeupdate` event dispatched, the same way
// a real element would.
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import { parseVtt } from './captionCues.js'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The media arrives as an authenticated fetch through api.js, so that is what is stubbed — NOT
// `window.fetch`. Stubbing the global would let a component that hand-rolls its own request (with
// no bearer, no X-Auth-Provider and no BASE, which is exactly the bug this file now pins) pass
// here and fail for every signed-in user. Mocking the module means the only way to be green is to
// go through the layer that carries those.
vi.mock('./api.js', () => ({ getFileContentBlob: vi.fn() }))
import { getFileContentBlob } from './api.js'
import CaptionEditor from './CaptionEditor.jsx'

const here = dirname(fileURLToPath(import.meta.url))

afterEach(() => unmountAll())

// jsdom implements neither of these; the component's whole media path runs through them.
let revoked = []
beforeEach(() => {
  revoked = []
  let n = 0
  getFileContentBlob.mockReset()
  getFileContentBlob.mockResolvedValue(new Blob(['fake bytes'], { type: 'video/mp4' }))
  URL.createObjectURL = vi.fn(() => `blob:acp/${n++}`)
  URL.revokeObjectURL = vi.fn((u) => revoked.push(u))
})

const VTT = 'WEBVTT\nLanguage: en\n\nNOTE\nDrafted by ACP using tiny; awaiting human approval.\n\n'
  + '1\n00:00:00.000 --> 00:00:02.400\nWelcome to the quarterly all-hands.\n\n'
  + '2\n00:00:02.440 --> 00:00:04.200\nFirst, a word on the accessibility\n\n'
  + '3\n00:00:04.240 --> 00:00:06.900\nprogramme and what it means.\n'

const TRANSCRIPT = '[00:00:00] Welcome to the quarterly all-hands.\n'

// `load` defaults to true because almost every test here is about what the reviewer does ONCE
// the media is playing. The restraint itself — that nothing is fetched until they ask — is what
// `load: false` is for, and it has its own tests below.
async function mount(props = {}) {
  const { load = true, ...rest } = props
  const { container, root } = createTestRoot()
  const state = { value: rest.value ?? VTT }
  const onChange = rest.onChange || ((v) => { state.value = v })
  await act(async () => {
    root.render(createElement(CaptionEditor, {
      scanId: 's1', mediaKind: 'video', filename: 'townhall.mp4',
      ...rest, value: state.value, onChange,
    }))
  })
  if (load) await loadMedia(container)
  return { container, state, root, onChange }
}

async function loadMedia(container) {
  const btn = container.querySelector('.caption-editor-loadbtn')
  if (!btn) return null
  await act(async () => { btn.click() })
  return container.querySelector('video, audio')
}

const cueRows = (c) => [...c.querySelectorAll('.caption-cue')]
const textareas = (c) => [...c.querySelectorAll('.caption-cue-text textarea')]
const seekButtons = (c) => [...c.querySelectorAll('.caption-cue-time')]

async function playTo(container, seconds) {
  const el = container.querySelector('video, audio')
  await act(async () => {
    el.currentTime = seconds
    el.dispatchEvent(new Event('timeupdate'))
  })
}

async function typeInto(el, value) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

describe('the media is playable at all', () => {
  it('plays the scanned file, fetched through the authenticated API layer', async () => {
    // WHAT THIS REPLACED, and why the assertion moved from an attribute to a call. The element
    // used to carry src="/scans/s1/files/townhall.mp4/content" directly, and that string could
    // never have worked in production twice over: a browser sends no bearer with a media element
    // load, and a relative path resolves against the WEB origin, not the API host. Asserting the
    // attribute passed happily on both counts.
    const { container } = await mount()
    expect(getFileContentBlob).toHaveBeenCalledWith('s1', 'townhall.mp4')
    const video = container.querySelector('video')
    expect(video).toBeTruthy()
    expect(video.getAttribute('src')).toMatch(/^blob:/)
    expect(video.hasAttribute('controls')).toBe(true)
  })

  it('uses an audio element for an audio-only file', async () => {
    // A <video> tag on an .mp3 renders a black rectangle where the reviewer expects a transport,
    // which reads as a file that failed to load.
    const { container } = await mount({ mediaKind: 'audio', filename: 'interview.mp3' })
    expect(container.querySelector('audio')).toBeTruthy()
    expect(container.querySelector('video')).toBeNull()
  })

  it('downloads nothing until the reviewer asks for it', async () => {
    // A review queue holds many cards. Fetching every recording in full the moment its card
    // mounts would download an estate's worth of media nobody asked for.
    //
    // This used to be `preload="metadata"` on the element, which the browser honoured for free.
    // An authenticated fetch cannot be lazy that way — reading the response IS the download — so
    // the restraint became explicit, and this test moved with it rather than being deleted.
    const { container } = await mount({ load: false })
    expect(getFileContentBlob).not.toHaveBeenCalled()
    expect(container.querySelector('video')).toBeNull()

    await loadMedia(container)
    expect(getFileContentBlob).toHaveBeenCalledTimes(1)
    expect(container.querySelector('video')).toBeTruthy()
  })

  it('says what the control will do before the reviewer commits to a download', async () => {
    const { container } = await mount({ load: false })
    const btn = container.querySelector('.caption-editor-loadbtn')
    expect(btn.tagName).toBe('BUTTON')
    expect(btn.textContent).toBe('Load video')
    expect(container.textContent).toContain('townhall.mp4')
  })

  it('releases the blob URL when the card goes away', async () => {
    // A caption card holds a whole recording in memory behind that URL. A reviewer working
    // through a queue would accumulate every file they had played until the tab was closed.
    const { container } = await mount()
    const url = container.querySelector('video').getAttribute('src')
    await unmountAll()          // not root.unmount(): unmountAll owns the list, so the afterEach
    expect(revoked).toContain(url)   // that follows does not tear the same root down twice
  })

  it('says WHY there is no player rather than rendering a broken one', async () => {
    const { container } = await mount({ scanId: null })
    expect(container.querySelector('video')).toBeNull()
    expect(container.textContent).toContain('could not be located')
    // The editing surface must survive: a reviewer with their own copy of the file can still work.
    expect(textareas(container).length).toBeGreaterThan(0)
  })

  it('keeps the cues editable when the browser cannot play the codec', async () => {
    const { container } = await mount()
    await act(async () => {
      container.querySelector('video').dispatchEvent(new Event('error'))
    })
    expect(container.textContent).toContain('could not be played')
    expect(textareas(container).length).toBe(3)
  })
})

describe('synchronisation', () => {
  it('marks the cue under the playhead, and only that one', async () => {
    const { container } = await mount()
    await playTo(container, 1.0)
    const marked = cueRows(container).filter((r) => r.getAttribute('aria-current') === 'true')
    expect(marked).toHaveLength(1)
    expect(marked[0].textContent).toContain('Welcome to the quarterly all-hands.')
  })

  it('moves the mark as the media plays', async () => {
    const { container } = await mount()
    await playTo(container, 1.0)
    expect(cueRows(container)[0].getAttribute('aria-current')).toBe('true')
    await playTo(container, 3.0)
    expect(cueRows(container)[0].getAttribute('aria-current')).toBeNull()
    expect(cueRows(container)[1].getAttribute('aria-current')).toBe('true')
  })

  it('marks nothing in the gap between cues', async () => {
    // Cue 2 ends at 4.200 and cue 3 starts at 4.240. Highlighting a neighbour through the gap
    // would tell the reviewer a line is being spoken when the audio is silent.
    const { container } = await mount()
    await playTo(container, 4.22)
    expect(cueRows(container).some((r) => r.getAttribute('aria-current') === 'true')).toBe(false)
  })

  it('announces the position politely for a reviewer who cannot see the highlight', async () => {
    // This is an accessibility product; a caption tool that conveyed "which line" by colour alone
    // would fail the criterion it exists to serve.
    const { container } = await mount()
    const live = container.querySelector('[aria-live="polite"]')
    expect(live).toBeTruthy()
    await playTo(container, 3.0)
    expect(live.textContent).toContain('cue 2 of 3')
  })
})

describe('seeking', () => {
  it('jumps the media to a cue when its time is activated', async () => {
    const { container } = await mount()
    const video = container.querySelector('video')
    await act(async () => { seekButtons(container)[2].click() })
    expect(video.currentTime).toBeCloseTo(4.24, 3)
  })

  it('offers seeking as a real button, reachable by keyboard', async () => {
    // A <div onClick> would be invisible to Tab and to a screen reader. The label names the time
    // and the cue, because "00:00:04.240" alone tells a screen-reader user nothing about what
    // activating it does.
    const { container } = await mount()
    const btn = seekButtons(container)[2]
    expect(btn.tagName).toBe('BUTTON')
    expect(btn.getAttribute('type')).toBe('button')
    expect(btn.getAttribute('aria-label')).toBe('Play from 00:00:04.240, cue 3')
  })

  it('does not throw when the media element has nothing loaded', async () => {
    const { container } = await mount({ scanId: null })
    // No player at all — activating a cue must still be harmless rather than an exception that
    // takes the whole card down.
    await act(async () => { seekButtons(container)[0]?.click() })
    expect(container.textContent).toContain('could not be located')
  })
})

describe('correcting a line', () => {
  it('gives every cue its own labelled field', async () => {
    const { container } = await mount()
    expect(textareas(container)).toHaveLength(3)
    expect(textareas(container)[0].value).toBe('Welcome to the quarterly all-hands.')
    expect(container.textContent).toContain('Cue 1 text')
  })

  it('puts an edit back into the value as valid WebVTT', async () => {
    let latest = null
    const { container } = await mount({ onChange: (v) => { latest = v } })
    await typeInto(textareas(container)[0], 'Welcome to the quarterly All Hands.')

    expect(latest).toBeTruthy()
    const { cues } = parseVtt(latest)
    expect(cues[0].text).toBe('Welcome to the quarterly All Hands.')
    expect(cues).toHaveLength(3)
  })

  it('changes nothing except the cue that was edited', async () => {
    // Re-serialising must not silently re-time or re-number anything. A reviewer fixing one word
    // and finding their cue boundaries moved would have no way to know it happened.
    let latest = null
    const { container } = await mount({ onChange: (v) => { latest = v } })
    await typeInto(textareas(container)[1], 'First, a word on accessibility')

    const before = parseVtt(VTT)
    const after = parseVtt(latest)
    expect(after.header).toBe(before.header)
    expect(after.cues.map((c) => [c.id, c.start, c.end]))
      .toEqual(before.cues.map((c) => [c.id, c.start, c.end]))
    expect(after.cues[0].text).toBe(before.cues[0].text)
    expect(after.cues[2].text).toBe(before.cues[2].text)
  })

  it('keeps the provenance NOTE across an edit', async () => {
    // The NOTE records that a machine drafted this and a human approved it. Losing it on the
    // first save would erase the provenance from the artefact that ships.
    let latest = null
    const { container } = await mount({ onChange: (v) => { latest = v } })
    await typeInto(textareas(container)[0], 'Corrected.')
    expect(latest).toContain('awaiting human approval')
    expect(latest).toContain('Language: en')
  })
})

describe('a transcript is not a cue file', () => {
  it('renders prose in a plain editor, with the player still available', async () => {
    // 1.2.1 delivers flowing text with no timings. A cue list would show one enormous entry at
    // 00:00 and invite the reviewer to seek to a time that means nothing.
    const { container } = await mount({ value: TRANSCRIPT, mediaKind: 'audio',
                                        filename: 'interview.mp3' })
    expect(cueRows(container)).toHaveLength(0)
    expect(container.querySelector('audio')).toBeTruthy()
    const box = container.querySelector('.caption-editor-prose textarea')
    expect(box.value).toBe(TRANSCRIPT)
  })

  it('edits prose straight through, without a round trip through the cue writer', async () => {
    let latest = null
    const { container } = await mount({ value: TRANSCRIPT, onChange: (v) => { latest = v } })
    await typeInto(container.querySelector('.caption-editor-prose textarea'), 'Corrected prose.')
    expect(latest).toBe('Corrected prose.')
  })
})

describe('an empty caption file', () => {
  it('says so rather than showing an editor with nothing in it', async () => {
    // Approving an empty cue file delivers an empty caption track, which reads to a player as
    // "captions provided" and to a viewer as silence.
    const { container } = await mount({ value: 'WEBVTT\n' })
    expect(cueRows(container)).toHaveLength(0)
    expect(container.textContent).toContain('no cues')
  })
})


describe('the classes it uses actually exist', () => {
  it('every caption-* class the component renders has a rule in styles.css', () => {
    // A className with no rule renders as nothing and looks like a layout bug nobody wrote.
    const css = readFileSync(join(here, 'styles.css'), 'utf8')
    const src = readFileSync(join(here, 'CaptionEditor.jsx'), 'utf8')
    const used = new Set([...src.matchAll(/caption-[a-z-]+/g)].map((m) => m[0]))
    const missing = [...used].filter((cls) => !css.includes(`.${cls}`))
    expect(missing).toEqual([])
    expect(used.size).toBeGreaterThan(4)
  })

  it("uses the repo's own screen-reader-only class, not an invented one", () => {
    // The first draft used `sr-only`. This repo's utility is `.sronly` — so the live-region
    // announcement and the per-cue field labels would have rendered VISIBLY, as stray text in the
    // middle of the card. Every other assertion in this file still passed, because textContent
    // reads the same whether the text is hidden or not.
    const css = readFileSync(join(here, 'styles.css'), 'utf8')
    const src = readFileSync(join(here, 'CaptionEditor.jsx'), 'utf8')
    expect(src).not.toMatch(/className="sr-only"/)
    expect(src).toMatch(/className="sronly"/)
    expect(css).toMatch(/\.sronly\s*\{/)
  })

  it('marks the playing cue by more than colour', async () => {
    // 1.4.1 Use of Color is a criterion this product enforces on other people's documents.
    // Conveying "this is the line playing" with a hue alone would fail it in our own UI.
    const css = readFileSync(join(here, 'styles.css'), 'utf8')
    const rule = css.slice(css.indexOf('.caption-cue-active'))
    expect(rule).toMatch(/border-left-color/)
    expect(css).toMatch(/\.caption-cue-active \.caption-cue-text textarea \{ font-weight/)
    // …and the fact reaches assistive technology independently of any of it.
    const { container } = await mount()
    await playTo(container, 1.0)
    expect(container.querySelector('[aria-current="true"]')).toBeTruthy()
  })
})
