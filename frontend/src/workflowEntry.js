// Entering Remediate from the main workflow starts a new planning visit. A mode left
// in the address by a previous visit must not select Live for the next assessment.
export function prepareWorkflowEntry(next) {
  if (next !== 'remediate') return
  try {
    const url = new URL(window.location.href)
    url.searchParams.set('tab', 'remediate')
    url.searchParams.set('mode', 'plan')
    window.history.replaceState(window.history.state, '', url)
    // Also refresh an already-mounted workspace when its main tab is clicked again.
    window.dispatchEvent(new PopStateEvent('popstate'))
  } catch { /* Navigation remains usable where history is unavailable. */ }
}
