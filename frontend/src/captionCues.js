// Parse and re-serialise WebVTT in the browser, for the caption review editor.
//
// WHY A SECOND IMPLEMENTATION EXISTS AT ALL, and why it is deliberately smaller than the first.
// `api/captions.py` writes the file and parses it back on the server. The editor cannot use it:
// the reviewer's corrections happen in a browser, on a value held in React state, between
// keystrokes. Round-tripping every edit through the API would put a network call in the path of
// typing.
//
// Two implementations of one format is a real cost, so the split is drawn where it is cheapest:
// this one PRESERVES rather than decides. It never re-segments, never re-wraps, never renumbers
// beyond what it read, and never invents a timing. Python owns "what should the cues be"; this
// owns "show me the cues that are there and put my edit back where it came from". Everything
// this file could get wrong about segmentation is a decision it does not make.
//
// `captionCues.test.js` round-trips fixtures produced by the PYTHON writer, byte for byte, so the
// two cannot drift on the parts they share.

// HH:MM:SS.mmm, and also MM:SS.mmm — WebVTT permits the short form and real files in the wild use
// it, so a parser that only accepted the long one would silently read a valid file as having no
// cues, which renders as "this caption file is empty" rather than as an error.
const TIME = /^(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})$/

export function parseTimestamp(raw) {
  const m = TIME.exec(String(raw || '').trim())
  if (!m) return null
  const [, h, mm, ss, ms] = m
  const seconds = Number(h || 0) * 3600 + Number(mm) * 60 + Number(ss)
    + Number(String(ms).padEnd(3, '0')) / 1000
  return Number.isFinite(seconds) ? seconds : null
}

export function formatTimestamp(seconds) {
  const s = Math.max(0, Number(seconds) || 0)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  const ms = Math.round((s - Math.floor(s)) * 1000)
  const p = (n, w = 2) => String(n).padStart(w, '0')
  return `${p(h)}:${p(m)}:${p(sec)}.${p(ms, 3)}`
}

// WebVTT escapes these three in cue text; the editor shows and edits the real characters, so they
// are decoded on the way in and re-encoded on the way out. Skipping the round trip would show a
// reviewer `&amp;` where the video says "and", and — worse — would double-escape it on save.
const decode = (t) => String(t).replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
const encode = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/**
 * Split a WebVTT document into { header, cues }.
 *
 * `header` is everything before the first cue — the WEBVTT line, any Language:, any NOTE block —
 * and it is carried through UNPARSED and re-emitted verbatim. The NOTE this pipeline writes says
 * the file was machine-drafted and is awaiting human approval; a serialiser that rebuilt the
 * header from what it understood would drop that provenance the first time a reviewer saved.
 */
export function parseVtt(text) {
  const raw = String(text || '').replace(/\r\n?/g, '\n')
  const blocks = raw.split(/\n{2,}/)
  const header = []
  const cues = []
  let seenCue = false

  for (const block of blocks) {
    const lines = block.split('\n').filter((l, i) => !(i === 0 && l.trim() === ''))
    if (!lines.length || lines.every((l) => !l.trim())) continue

    // A cue block is identified by its ARROW LINE, which may be the first or second line (an
    // optional identifier precedes it). Anything with no arrow before the first cue is header.
    let arrowAt = -1
    for (let i = 0; i < Math.min(2, lines.length); i++) {
      if (lines[i].includes('-->')) { arrowAt = i; break }
    }
    if (arrowAt === -1) {
      if (!seenCue) header.push(block)
      // NOTE/STYLE/REGION blocks between cues are valid WebVTT. Dropping them would silently
      // corrupt a file the reviewer opens and saves without changing anything. Attach them to
      // the preceding cue so serialiseVtt can re-insert them in the right position.
      else if (cues.length) (cues[cues.length - 1].trailing ??= []).push(block.replace(/\n+$/, ''))
      continue
    }
    const [startRaw, rest] = lines[arrowAt].split('-->')
    const endRaw = String(rest || '').trim().split(/\s+/)[0]
    const start = parseTimestamp(startRaw)
    const end = parseTimestamp(endRaw)
    if (start === null || end === null) {
      if (!seenCue) header.push(block)
      continue
    }
    seenCue = true
    cues.push({
      id: arrowAt === 1 ? lines[0].trim() : '',
      start,
      end,
      // Trailing newlines stripped, and this is not cosmetic. Splitting on blank lines leaves
      // the FINAL block holding the file's own terminating newline, so the last cue's text came
      // back as "…the end.\n" — which failed the byte-for-byte round trip against the Python
      // writer and would have appended a blank line to that cue every time a reviewer saved.
      // A blank line terminates a cue in WebVTT, so text never legitimately ends with one.
      text: decode(lines.slice(arrowAt + 1).join('\n')).replace(/\n+$/, ''),
    })
  }
  return { header: header.join('\n\n'), cues }
}

/**
 * Rebuild a WebVTT document from a header and cues.
 *
 * The header is emitted verbatim, defaulting to a bare `WEBVTT` only when there was none —
 * inventing a Language: or a NOTE would be asserting something nobody said.
 */
export function serialiseVtt(header, cues) {
  const head = (header || '').trim() || 'WEBVTT'
  const body = (cues || []).flatMap((c, i) => {
    const id = (c.id || '').trim() || String(i + 1)
    const cueStr = `${id}\n${formatTimestamp(c.start)} --> ${formatTimestamp(c.end)}\n${encode(c.text)}`
    return [cueStr, ...(c.trailing || [])]
  })
  return [head, ...body].join('\n\n') + '\n'
}

/** True when the text looks like a cue file rather than a plain transcript. */
export function isVtt(text) {
  return /^﻿?WEBVTT\b/.test(String(text || '').trimStart())
}

/**
 * The cue playing at `t`, or -1.
 *
 * Ties go to the EARLIER cue (`t < end`, not `<=`): consecutive cues share a boundary in the
 * files this pipeline writes, and `<=` would light both for one frame — which reads on screen as
 * a flicker with no cause.
 */
export function activeCueIndex(cues, t) {
  const time = Number(t)
  if (!Number.isFinite(time)) return -1
  return (cues || []).findIndex((c) => time >= c.start && time < c.end)
}
