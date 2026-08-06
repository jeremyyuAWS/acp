// 1.2.2 Captions (Prerecorded) (Level A)
// Prerecorded video with audio needs synchronized captions.
// Detect-and-route: a <video> with no captions/subtitles track is flagged and
// sent to human review — captions can't be authored deterministically (they need
// the actual audio; MDK's Whisper path can draft them, but that's a server step,
// not a markup fix). fixMode 'human-only' → the finding routes to HITL, never
// silently auto-passed.

export const meta = {
  id: '1.2.2',
  level: 'A',
  name: 'Captions (Prerecorded)',
  fixMode: 'human-only', // captions need the audio track — a reviewer/Whisper adds them
}

const hasCaptions = (v) =>
  [...v.querySelectorAll('track')].some((t) => {
    const k = (t.getAttribute('kind') || '').toLowerCase()
    return k === 'captions' || k === 'subtitles'
  })

export function check(doc) {
  const findings = []
  doc.querySelectorAll('video').forEach((v) => {
    if (hasCaptions(v)) return
    findings.push({
      element: v.outerHTML.slice(0, 120),
      detail: 'Video has no captions track — deaf/hard-of-hearing users miss the audio',
      severity: 'SERIOUS',
    })
  })
  return findings
}

// No deterministic fix — detection only; the orchestrator routes human-only
// findings to the HITL queue. Present for interface consistency.
export function fix() {
  return new Set()
}
