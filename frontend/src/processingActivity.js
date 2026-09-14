// Format action language only. File paths are rendered separately and never rewritten.
export function titleCaseStep(value) {
  return String(value || '').replace(/\b[a-z]+\b/gi, word => {
    if (/^[A-Z\d-]+$/.test(word)) return word
    return word[0].toUpperCase() + word.slice(1)
  })
}

const remediationPhases = new Set(['remediating', 'downloading', 'storing', 'verifying', 'publishing'])
export function isRemediationActivity(activity) {
  return activity?.stage === 'remediate' || remediationPhases.has(activity?.phase)
}
export function remediationStep(activity) {
  const action = String(activity?.action || '')
  if (/^describing images?\b/i.test(action)) return titleCaseStep(action.replace(/^describing/i, 'Generating Alt Text For'))
  return titleCaseStep(action)
}
