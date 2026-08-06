// 1.2.1 Audio-only & Video-only (Prerecorded) (Level A)
// Prerecorded audio-only content needs a text transcript. (Video-only needs a
// transcript or audio track, but "video-only — no audio" can't be told from
// markup, so this rule scopes to <audio>, the deterministically-detectable case.)
// Detect-and-route: <audio> with no linked transcript is flagged for review.

export const meta = {
  id: '1.2.1',
  level: 'A',
  name: 'Audio-only & Video-only (Prerecorded)',
  fixMode: 'human-only', // a transcript must be authored from the audio — human
}

// A transcript is signalled by aria-describedby (points at the transcript text)
// or an aria-label naming one; captions tracks don't substitute for a transcript.
const hasTranscript = (a) =>
  Boolean(a.getAttribute('aria-describedby') || /transcript/i.test(a.getAttribute('aria-label') || ''))

export function check(doc) {
  const findings = []
  doc.querySelectorAll('audio').forEach((a) => {
    if (hasTranscript(a)) return
    findings.push({
      element: a.outerHTML.slice(0, 120),
      detail: 'Audio-only content has no transcript — deaf/hard-of-hearing users get nothing',
      severity: 'SERIOUS',
    })
  })
  return findings
}

export function fix() {
  return new Set()
}
