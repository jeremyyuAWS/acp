import { useEffect, useMemo, useRef, useState } from 'react'
import { parseVtt, serialiseVtt, formatTimestamp, isVtt, activeCueIndex } from './captionCues.js'

// The synchronised caption review editor.
//
// WHAT WAS WRONG WITHOUT IT. Slices 1-4 gave a reviewer a machine transcript in a two-row
// <textarea> and a card telling them "speech recognition mishears names, numbers and homophones".
// Checking that claim means hearing the audio at the moment each line is spoken, and a plain box
// holding a whole WebVTT file makes that impossible: there is no audio, and the timings are wire
// format the reviewer has to decode in their head to know which line they are looking at.
//
// So the correction task ACP asked for could not actually be performed. This makes it performable
// — the media plays, the cue under the playhead is highlighted, clicking a cue seeks to it, and
// each cue's text is its own field.
//
// IT IS AN ACCESSIBILITY PRODUCT, so the editor is operable without a mouse and legible to a
// screen reader: every cue is a real <button> for seeking followed by a labelled <textarea>, so
// Tab reaches everything and Enter/Space activate the seek; the active cue is marked with
// aria-current; and the "now playing" announcement is a polite live region rather than a colour
// change. A caption tool a blind reviewer could not use would be an embarrassment on this of all
// products.
//
// PARSING IS PRESERVING, NOT DECIDING — see captionCues.js. Nothing here re-segments or re-times.
// A reviewer fixing a word must not have their cue boundaries silently rewritten underneath them,
// and re-segmentation is `api/captions.py`'s decision, made once, at drafting time.

export default function CaptionEditor({ value, onChange, mediaSrc, mediaKind = 'video',
                                        filename = '', disabled = false }) {
  const mediaRef = useRef(null)
  const [now, setNow] = useState(0)
  const [mediaError, setMediaError] = useState(null)

  // Re-parsed from `value` on every render rather than held in state. The card owns the value —
  // it is what gets approved — and a second copy here would be one more thing that can disagree
  // with what the reviewer is about to sign.
  const { header, cues } = useMemo(() => parseVtt(value), [value])
  const cueFile = isVtt(value)
  const active = activeCueIndex(cues, now)

  useEffect(() => {
    const el = mediaRef.current
    if (!el) return
    const tick = () => setNow(el.currentTime || 0)
    el.addEventListener('timeupdate', tick)
    // `seeked` too: dragging the scrubber while paused fires no timeupdate in some browsers, and
    // the highlight would sit on the cue the reviewer left rather than the one they moved to.
    el.addEventListener('seeked', tick)
    return () => { el.removeEventListener('timeupdate', tick); el.removeEventListener('seeked', tick) }
  }, [mediaSrc])

  const seekTo = (t) => {
    const el = mediaRef.current
    if (!el) return
    try { el.currentTime = t } catch { /* a media element with nothing loaded throws; harmless */ }
    setNow(t)
  }

  const editCue = (i, text) => {
    const next = cues.map((c, j) => (j === i ? { ...c, text } : c))
    onChange(serialiseVtt(header, next))
  }

  // A TRANSCRIPT IS NOT A CUE FILE. 1.2.1 delivers prose with no timings; rendering it here would
  // show one enormous cue at 00:00 and invite the reviewer to "seek" to a time that means
  // nothing. The plain editor is the honest surface for it — with the player still present,
  // because checking prose against the audio is the same job.
  if (!cueFile) {
    return (
      <div className="caption-editor">
        <MediaPlayer refEl={mediaRef} src={mediaSrc} kind={mediaKind} filename={filename}
                     error={mediaError} onError={setMediaError} />
        <label className="caption-editor-prose">
          <span className="muted" style={{ fontSize: 12 }}>
            Transcript — check it against the recording before approving
          </span>
          <textarea className="evcard-rec-input" rows={10} value={value} disabled={disabled}
                    onChange={(e) => onChange(e.target.value)} />
        </label>
      </div>
    )
  }

  return (
    <div className="caption-editor">
      <MediaPlayer refEl={mediaRef} src={mediaSrc} kind={mediaKind} filename={filename}
                   error={mediaError} onError={setMediaError} />

      {/* The announcement a sighted reviewer gets from the highlight. `polite` so it waits for a
          gap rather than interrupting, and it names the cue rather than reading its text — the
          text is already on screen in a field the reviewer can reach. */}
      <p className="sronly" role="status" aria-live="polite">
        {active >= 0 ? `Playing cue ${active + 1} of ${cues.length}` : 'Between cues'}
      </p>

      {cues.length === 0 ? (
        <p className="muted" style={{ fontSize: 12.5 }}>
          This caption file has no cues. Approving it would deliver an empty caption track.
        </p>
      ) : (
        <ol className="caption-editor-cues">
          {cues.map((c, i) => (
            <li key={i} className={`caption-cue${i === active ? ' caption-cue-active' : ''}`}
                aria-current={i === active ? 'true' : undefined}>
              <button type="button" className="caption-cue-time"
                      onClick={() => seekTo(c.start)}
                      aria-label={`Play from ${formatTimestamp(c.start)}, cue ${i + 1}`}>
                {formatTimestamp(c.start)}
              </button>
              <label className="caption-cue-text">
                <span className="sronly">{`Cue ${i + 1} text`}</span>
                <textarea rows={2} value={c.text} disabled={disabled}
                          onChange={(e) => editCue(i, e.target.value)} />
              </label>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

function MediaPlayer({ refEl, src, kind, filename, error, onError }) {
  // NO PLAYER WITHOUT A SOURCE, and no silent absence either. A <video> with src="" renders a
  // broken control that looks like the file failed to load; saying why is the difference between
  // "this is broken" and "this scan has no retrievable original".
  if (!src) {
    return (
      <p className="muted" style={{ fontSize: 12.5 }}>
        The original media could not be located for this scan, so it cannot be played here.
        Check the draft against your own copy of {filename || 'the file'} before approving.
      </p>
    )
  }
  if (error) {
    return (
      <p role="status" className="muted" style={{ fontSize: 12.5 }}>
        {filename || 'This file'} could not be played in the browser — it may use a codec your
        browser does not support. The caption text below is still editable; check it against
        your own copy before approving.
      </p>
    )
  }
  const Tag = kind === 'audio' ? 'audio' : 'video'
  return (
    // `controls` always: the reviewer needs play, pause and volume, and building our own would
    // mean re-implementing keyboard support the browser already gets right.
    // `preload="metadata"` because a review queue can hold many cards and fetching every video in
    // full on render would download an estate's worth of media nobody asked for.
    <Tag ref={refEl} src={src} controls preload="metadata" className="caption-editor-media"
         onError={() => onError('media')} />
  )
}
