// 1.2.3 Audio Description or Media Alternative (Prerecorded) (Level A)
// Prerecorded video needs either an audio-description track or a full text
// alternative (transcript) covering the visual information.
// Detect-and-route: a <video> with neither a descriptions track nor a linked
// transcript (aria-describedby) is flagged for human review. fixMode 'human-only'.

export const meta = {
  id: '1.2.3',
  level: 'A',
  name: 'Audio Description or Media Alternative',
  fixMode: 'human-only', // needs a described track or authored transcript — human
}

const hasDescriptionOrTranscript = (v) =>
  [...v.querySelectorAll('track')].some((t) => (t.getAttribute('kind') || '').toLowerCase() === 'descriptions')
  || Boolean(v.getAttribute('aria-describedby'))

export function check(doc) {
  const findings = []
  doc.querySelectorAll('video').forEach((v) => {
    if (hasDescriptionOrTranscript(v)) return
    findings.push({
      element: v.outerHTML.slice(0, 120),
      detail: 'Video has no audio description or transcript — blind users miss on-screen action',
      severity: 'SERIOUS',
    })
  })
  return findings
}

export function fix() {
  return new Set()
}
