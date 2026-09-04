// The caption editor REACHED FROM THE CARD — the assertion that stops it becoming an orphan.
//
// `captionEditor.test.jsx` renders the component directly and proves it works. That says nothing
// about whether anything mounts it, and this repo has the receipts on that distinction:
// `tests/test_orphaned_detectors.py` records three detectors declared and never invoked, reading
// as capability for months, and `unmountedComponents.test.jsx` exists because ten components sat
// on main that nothing rendered. A caption editor nothing renders is the same failure with a
// nicer test suite behind it.
//
// So this mounts the REAL EvidenceCard with a real companion proposal and asserts the reviewer
// gets the player and the cue list — through the card's own `editable`/`companionRow` gates,
// which is the wiring that could break.
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

vi.mock('./api.js', () => ({
  suggestFix: () => Promise.resolve({}),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getSourceLink: () => Promise.resolve({ url: null }),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
  getFileContentBlob: vi.fn(() => Promise.resolve(new Blob(['fake'], { type: 'video/mp4' }))),
}))

const { getFileContentBlob } = await import('./api.js')
URL.createObjectURL = vi.fn(() => 'blob:acp/card')
URL.revokeObjectURL = vi.fn()
beforeEach(() => getFileContentBlob.mockClear())

/** The reviewer's click on "Load video" — the media is fetched on request, not on render. */
async function loadMedia(c) {
  const btn = c.querySelector('.caption-editor-loadbtn')
  await act(async () => { btn.click() })
  return c.querySelector('video, audio')
}

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

const VTT = 'WEBVTT\nLanguage: en\n\n1\n00:00:00.000 --> 00:00:02.400\n'
  + 'Welcome to the quarterly all-hands.\n\n'
  + '2\n00:00:02.440 --> 00:00:04.200\nFirst, a word on accessibility.\n'

const captionRow = (over = {}) => ({
  id: 42, scan_id: 's1', file: 'townhall.mp4', rule_id: '1.2.2',
  rule_name: 'Captions (Prerecorded)', status: 'pending', finding_count: 1,
  proposals: [{
    locator: 'townhall.mp4', before: '', proposed_value: VTT,
    rationale: '2 cues drafted from the soundtrack by local speech recognition.',
    source: 'local speech recognition (tiny) — companion file, not written into the media',
    companion_file: 'townhall.en.vtt', sc: '1.2.2',
    why_review: 'Every word here was written by a machine listening to audio nobody has checked.',
  }],
  ...over,
})

const mount = async (item) => {
  const { container, root } = createTestRoot()
  const onAct = vi.fn().mockResolvedValue(undefined)
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct, editable: true })) })
  return container
}

describe('a caption card gives the reviewer the editor, not a text box', () => {
  it('renders the cue list and the player', async () => {
    const c = await mount(captionRow())
    expect(c.querySelectorAll('.caption-cue')).toHaveLength(2)
    expect(await loadMedia(c)).toBeTruthy()
  })

  it('points the player at the media this card is about', async () => {
    // The proposal's locator is the media filename. Getting this wrong would play a DIFFERENT
    // file behind the captions — and it would look like it was working.
    //
    // Asserted as the call the card causes, not as a src attribute. The card used to hand the
    // editor a hand-built `/scans/.../content` string; that carried no bearer and no API base,
    // so it named the right file and could not have fetched it for any signed-in user.
    const c = await mount(captionRow())
    await loadMedia(c)
    expect(getFileContentBlob).toHaveBeenCalledWith('s1', 'townhall.mp4')
  })

  it('uses an audio player for an audio-only card', async () => {
    const c = await mount(captionRow({
      file: 'interview.mp3', rule_id: '1.2.1', rule_name: 'Audio-only & Video-only',
      proposals: [{
        locator: 'interview.mp3', before: '', proposed_value: '[00:00:00] Welcome.\n',
        rationale: 'A timestamped transcript.', source: 'local speech recognition (tiny)',
        companion_file: 'interview.en.txt', sc: '1.2.1',
      }],
    }))
    await loadMedia(c)
    expect(c.querySelector('audio')).toBeTruthy()
    expect(c.querySelector('video')).toBeNull()
  })

  it('does NOT render the editor for an ordinary alt-text card', async () => {
    // The control. A cue editor on a 1.1.1 image row would show an empty cue list and a player
    // for a .docx — and would mean `companionRow` had stopped discriminating.
    const c = await mount({
      id: 43, scan_id: 's1', file: 'report.docx', rule_id: '1.1.1',
      rule_name: 'Non-text Content', status: 'pending', finding_count: 1,
      proposals: [{ locator: 'word/media/image1.png', before: '', proposed_value: 'A bar chart',
                    rationale: 'vision', source: 'llava', sc: '1.1.1' }],
    })
    expect(c.querySelectorAll('.caption-cue')).toHaveLength(0)
    expect(c.querySelector('video')).toBeNull()
    expect(c.querySelector('.evcard-rec-input')).toBeTruthy()
  })

  it('still offers the download beside the editor', async () => {
    // Editing and obtaining are different needs: a reviewer may want the file in their own player
    // before deciding. #1185 added the link; this makes sure the editor did not displace it.
    const c = await mount(captionRow())
    const link = c.querySelector('.evcard-companion-download a')
    expect(link).toBeTruthy()
    expect(link.getAttribute('href')).toBe('/hitl/queue/42/companion')
  })
})
