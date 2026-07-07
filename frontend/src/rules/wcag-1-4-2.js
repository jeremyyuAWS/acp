// 1.4.2 Audio Control (Level A)
// Audio that plays automatically for more than 3 seconds can be paused/stopped.
// Fix: deterministic — autoplaying media without controls gets the autoplay
//   removed and a controls attribute added, so the user decides when it plays.

export const meta = {
  id: '1.4.2',
  level: 'A',
  name: 'Audio Control',
  fixMode: 'auto', // removing autoplay / adding controls is always safe
}

const needsControl = (m) => m.hasAttribute('autoplay') && !m.hasAttribute('controls')

export function check(doc) {
  const findings = []
  doc.querySelectorAll('audio, video').forEach((m) => {
    if (!needsControl(m)) return
    findings.push({
      element: m.outerHTML.slice(0, 120),
      detail: 'Media autoplays with no way to pause or stop it',
      severity: 'SERIOUS',
    })
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  doc.querySelectorAll('audio, video').forEach((m) => {
    if (!needsControl(m)) return
    m.removeAttribute('autoplay')
    m.setAttribute('controls', '')
    changes.add('Stopped autoplaying media and added player controls · 1.4.2')
  })
  return changes
}
