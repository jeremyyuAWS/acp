import { useEffect, useRef, useState } from 'react'
import RemediationRunCard from './RemediationRunCard.jsx'

const MODES = ['review', 'live']

function modeFromLocation() {
  try {
    const mode = new URLSearchParams(window.location.search).get('mode')
    return MODES.includes(mode) ? mode : null
  } catch { return null }
}

function storedMode(runId) {
  try {
    const mode = sessionStorage.getItem(`acp-remediation-mode-${runId || 'none'}`)
    return MODES.includes(mode) ? mode : null
  } catch { return null }
}

export default function RemediationWorkspaceTabs({ runId, reviewCount = 0, snapshot = null,
  receivedAt = null, connected = false, review, live }) {
  // Null means the user has not chosen: the live server facts may still select the best default.
  const [chosen, setChosen] = useState(() => modeFromLocation() || storedMode(runId))
  const liveHeading = useRef(null)
  const tabs = useRef([])
  const activeWork = !!snapshot && !snapshot.terminal && snapshot.state !== 'draft'
  const mode = chosen || (reviewCount > 0 ? 'review' : activeWork ? 'live' : 'review')

  useEffect(() => {
    setChosen(modeFromLocation() || storedMode(runId))
  }, [runId])

  useEffect(() => {
    const restore = () => setChosen(modeFromLocation() || storedMode(runId))
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [runId])

  const select = (next, { focusPanel = false } = {}) => {
    setChosen(next)
    try {
      sessionStorage.setItem(`acp-remediation-mode-${runId || 'none'}`, next)
      const url = new URL(window.location.href)
      url.searchParams.set('tab', 'remediate')
      url.searchParams.set('mode', next)
      history.pushState({}, '', url)
    } catch { /* navigation state is progressive enhancement */ }
    if (focusPanel && next === 'live') requestAnimationFrame(() => liveHeading.current?.focus())
  }

  const onKeyDown = (event, index) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? MODES.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + MODES.length) % MODES.length
    select(MODES[nextIndex])
    tabs.current[nextIndex]?.focus()
  }

  return <>
    <RemediationRunCard snapshot={snapshot} receivedAt={receivedAt} connected={connected}
      onOpen={() => select('live', { focusPanel: true })} />
    <div className="rem-workspace-tabs" role="tablist" aria-label="Remediation workspace">
      <button ref={(node) => { tabs.current[0] = node }} type="button" role="tab"
        id="rem-mode-review" aria-controls="rem-panel-review" aria-selected={mode === 'review'}
        tabIndex={mode === 'review' ? 0 : -1} onKeyDown={(event) => onKeyDown(event, 0)}
        onClick={() => select('review')}>
        Review &amp; Approve <span>{reviewCount.toLocaleString()}</span>
      </button>
      <button ref={(node) => { tabs.current[1] = node }} type="button" role="tab"
        id="rem-mode-live" aria-controls="rem-panel-live" aria-selected={mode === 'live'}
        tabIndex={mode === 'live' ? 0 : -1} onKeyDown={(event) => onKeyDown(event, 1)}
        onClick={() => select('live')}>
        Live Processing {activeWork && <span className="rem-mode-live-dot" aria-label="active">●</span>}
      </button>
    </div>
    <div id="rem-panel-review" role="tabpanel" aria-labelledby="rem-mode-review"
      hidden={mode !== 'review'}>{review}</div>
    <div id="rem-panel-live" role="tabpanel" aria-labelledby="rem-mode-live"
      hidden={mode !== 'live'}>
      <h2 ref={liveHeading} tabIndex={-1} className="sr-only">Live Processing</h2>
      {live}
    </div>
  </>
}
