// The browser-side WebVTT parser, held against files the PYTHON writer actually produced.
//
// Two implementations of one format is the risk this file exists to bound. The fixtures below are
// not hand-typed: they are the literal output of `api/captions.py::to_webvtt` for a real
// transcript, pasted verbatim, so a change on either side that breaks the round trip fails here
// rather than in a reviewer's browser.
import { describe, it, expect } from 'vitest'
import { parseVtt, serialiseVtt, parseTimestamp, formatTimestamp, isVtt, activeCueIndex }
  from './captionCues.js'

// Straight from `to_webvtt(segment_cues(...), language='en', note=...)`. Note what it carries:
// a Language: line, a NOTE recording that a machine drafted it, cues re-segmented for reading
// speed (segment 2 became cues 2 and 3), a two-line cue, and escaped `&` and `<>`.
const PY_OUTPUT = 'WEBVTT\nLanguage: en\n\nNOTE\nDrafted by ACP using tiny; awaiting human approval.\n\n'
  + '1\n00:00:00.000 --> 00:00:02.400\nWelcome to the quarterly all-hands.\n\n'
  + '2\n00:00:02.440 --> 00:00:04.200\nFirst, a word on the accessibility\n\n'
  + '3\n00:00:04.240 --> 00:00:06.900\nprogramme and what it means for the\nteam this year.\n\n'
  + '4\n00:00:07.000 --> 00:00:09.000\nQuestions &amp; answers &lt;at the end&gt;.\n'

describe('reading what the server wrote', () => {
  it('finds every cue, with its timings and text', () => {
    const { cues } = parseVtt(PY_OUTPUT)
    expect(cues).toHaveLength(4)
    expect(cues[0]).toMatchObject({ id: '1', start: 0, end: 2.4 })
    expect(cues[0].text).toBe('Welcome to the quarterly all-hands.')
    expect(cues[2].text).toBe('programme and what it means for the\nteam this year.')
    expect(cues[3].start).toBeCloseTo(7.0, 3)
  })

  it('decodes the three characters WebVTT escapes', () => {
    // A reviewer must see what the video says, not the wire format. Showing `&amp;` is wrong on
    // screen and becomes `&amp;amp;` the moment they save.
    const { cues } = parseVtt(PY_OUTPUT)
    expect(cues[3].text).toBe('Questions & answers <at the end>.')
  })

  it('keeps the header — including the provenance NOTE — out of the cues', () => {
    const { header, cues } = parseVtt(PY_OUTPUT)
    expect(header).toContain('WEBVTT')
    expect(header).toContain('Language: en')
    expect(header).toContain('awaiting human approval')
    expect(cues.some((c) => c.text.includes('awaiting human approval'))).toBe(false)
  })
})

describe('writing it back', () => {
  it('round-trips the server\'s own output byte for byte', () => {
    // The assertion that makes a second implementation tolerable. If this ever fails, the two
    // parsers have diverged and a reviewer who opened a file and saved it without typing
    // anything would have changed it.
    const { header, cues } = parseVtt(PY_OUTPUT)
    expect(serialiseVtt(header, cues)).toBe(PY_OUTPUT)
  })

  it('re-escapes on the way out, exactly once', () => {
    const { header, cues } = parseVtt(PY_OUTPUT)
    cues[0].text = 'Tom & Jerry <live>'
    expect(serialiseVtt(header, cues)).toContain('Tom &amp; Jerry &lt;live&gt;')
    expect(serialiseVtt(header, cues)).not.toContain('&amp;amp;')
  })

  it('preserves an edit to one cue and nothing else', () => {
    const { header, cues } = parseVtt(PY_OUTPUT)
    cues[0].text = 'Welcome to the quarterly All Hands.'
    const out = serialiseVtt(header, cues)
    expect(out).toContain('Welcome to the quarterly All Hands.')
    expect(out).toContain('00:00:04.240 --> 00:00:06.900')
    expect(out).toContain('Language: en')
    expect(parseVtt(out).cues).toHaveLength(4)
  })

  it('invents no header when there was none', () => {
    // A Language: or a NOTE the reviewer never wrote would be a claim nobody made.
    const out = serialiseVtt('', [{ id: '', start: 0, end: 1, text: 'Hello' }])
    expect(out).toBe('WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHello\n')
  })
})

describe('files this pipeline did not write', () => {
  it('reads CRLF, the short MM:SS form, and comma decimals', () => {
    // WebVTT permits MM:SS; SRT uses a comma. A parser that rejected either would report a valid
    // file as having no cues, which renders as "empty" rather than as a problem.
    const { cues } = parseVtt('WEBVTT\r\n\r\n00:01.000 --> 00:02,500\r\nShort form\r\n')
    expect(cues).toHaveLength(1)
    expect(cues[0].start).toBeCloseTo(1, 3)
    expect(cues[0].end).toBeCloseTo(2.5, 3)
  })

  it('tolerates cues with no identifier line', () => {
    const { cues } = parseVtt('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nNo id here\n')
    expect(cues).toHaveLength(1)
    expect(cues[0].id).toBe('')
    // Serialising numbers them, because a cue needs SOME identifier and its position is the only
    // honest one available.
    expect(serialiseVtt('WEBVTT', cues)).toContain('1\n00:00:00.000')
  })

  it('does not mistake a plain transcript for a cue file', () => {
    // 1.2.1 delivers prose. Rendering it in a cue editor would show one enormous cue at 00:00.
    expect(isVtt('WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nHi\n')).toBe(true)
    expect(isVtt('[00:00:00] Welcome to the all-hands.\n')).toBe(false)
    expect(isVtt('')).toBe(false)
  })

  it('survives a malformed arrow line without losing the rest of the file', () => {
    const out = parseVtt('WEBVTT\n\nnot-a-time --> also-not\nJunk\n\n'
      + '00:00:05.000 --> 00:00:06.000\nReal cue\n')
    expect(out.cues).toHaveLength(1)
    expect(out.cues[0].text).toBe('Real cue')
  })
})

describe('timestamps', () => {
  it('round-trips a value through both directions', () => {
    for (const t of [0, 1.5, 62.25, 3661.007]) {
      expect(parseTimestamp(formatTimestamp(t))).toBeCloseTo(t, 3)
    }
  })

  it('rejects what is not a timestamp rather than guessing zero', () => {
    // Returning 0 for junk would place a cue at the start of the video and look like a real
    // timing, which is the failure mode that survives review.
    for (const bad of ['', 'soon', '99', null, undefined]) expect(parseTimestamp(bad)).toBe(null)
  })
})

describe('post-cue metadata blocks (NOTE / STYLE / REGION between cues)', () => {
  // WebVTT allows NOTE, STYLE and REGION blocks to appear after cues, not only before them.
  // Real captioning tools write post-cue NOTEs as provenance or QA records. Dropping them on
  // the first round-trip is silent corruption — the reviewer opened the file and the tool
  // deleted content without being asked.
  const WITH_POST_NOTE = 'WEBVTT\n\nNOTE\nPre-cue header note.\n\n'
    + '1\n00:00:00.000 --> 00:00:02.000\nFirst cue.\n\n'
    + 'NOTE\nBetween-cue annotation.\n\n'
    + '2\n00:00:02.000 --> 00:00:04.000\nSecond cue.\n\n'
    + 'NOTE\nTrailing annotation.\n'

  it('round-trips a file with post-cue NOTE blocks byte-for-byte', () => {
    const { header, cues } = parseVtt(WITH_POST_NOTE)
    expect(serialiseVtt(header, cues)).toBe(WITH_POST_NOTE)
  })

  it('keeps the pre-cue note in the header, not in any cue', () => {
    const { header, cues } = parseVtt(WITH_POST_NOTE)
    expect(header).toContain('Pre-cue header note')
    expect(cues.every((c) => !c.text.includes('Pre-cue header note'))).toBe(true)
  })

  it('still finds both cues', () => {
    const { cues } = parseVtt(WITH_POST_NOTE)
    expect(cues).toHaveLength(2)
    expect(cues[0].text).toBe('First cue.')
    expect(cues[1].text).toBe('Second cue.')
  })

  it('an edit to one cue leaves the between-cue and trailing notes intact', () => {
    const { header, cues } = parseVtt(WITH_POST_NOTE)
    cues[0].text = 'First cue edited.'
    const out = serialiseVtt(header, cues)
    expect(out).toContain('First cue edited.')
    expect(out).toContain('Between-cue annotation')
    expect(out).toContain('Trailing annotation')
  })
})

describe('which cue is playing', () => {
  const cues = [{ start: 0, end: 2 }, { start: 2, end: 4 }, { start: 5, end: 6 }]

  it('finds the cue containing the time', () => {
    expect(activeCueIndex(cues, 0)).toBe(0)
    expect(activeCueIndex(cues, 1.9)).toBe(0)
    expect(activeCueIndex(cues, 3)).toBe(1)
  })

  it('gives a shared boundary to the earlier cue', () => {
    // Consecutive cues touch in the files this pipeline writes. An inclusive end would light two
    // rows for one frame, which reads on screen as a flicker with no cause.
    expect(activeCueIndex(cues, 2)).toBe(1)
  })

  it('returns -1 in a gap, past the end, and for a time that is not a number', () => {
    expect(activeCueIndex(cues, 4.5)).toBe(-1)
    expect(activeCueIndex(cues, 99)).toBe(-1)
    expect(activeCueIndex(cues, NaN)).toBe(-1)
  })
})
