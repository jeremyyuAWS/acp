import { useEffect, useRef, useState } from 'react'
import useConfirmedRemediationActivity from './useConfirmedRemediationActivity.js'
const MODES = ['plan', 'live', 'review']

function modeFromLocation() {
  try {
    const mode = new URLSearchParams(window.location.search).get('mode')
    return MODES.includes(mode) ? mode : null
  } catch { return null }
}

export default function RemediationWorkspaceTabs({ runId, reviewCount = 0, snapshot = null,
  plan, review, live, workspaceRequest = null }) {
  // Open on Plan unless navigation explicitly names another tab. Background work and prior
  // session choices must not skip the planning screen.
  const [chosen, setChosen] = useState(() => modeFromLocation())
  const tabs = useRef([])
  const panels = useRef({})
  const pendingFocus = useRef(null)
  const cancelPanelFocus = () => {
    if (pendingFocus.current) cancelAnimationFrame(pendingFocus.current.id)
    pendingFocus.current = null
  }
  const lastWorkspaceRequest = useRef(workspaceRequest)
  const activeWork = useConfirmedRemediationActivity(snapshot)
  const mode = chosen || 'plan'

  useEffect(() => {
    cancelPanelFocus()
    setChosen(modeFromLocation())
    return cancelPanelFocus
  }, [runId])

  useEffect(() => {
    const restore = () => { cancelPanelFocus(); setChosen(modeFromLocation()) }
    window.addEventListener('popstate', restore)
    return () => window.removeEventListener('popstate', restore)
  }, [runId])

  const select = (next, { focusPanel = false } = {}) => {
    cancelPanelFocus()
    setChosen(next)
    try {
      const url = new URL(window.location.href)
      url.searchParams.set('tab', 'remediate')
      url.searchParams.set('mode', next)
      history.pushState({}, '', url)
    } catch { /* navigation state is progressive enhancement */ }
    if (focusPanel) {
      const request = { id: null }
      pendingFocus.current = request
      request.id = requestAnimationFrame(() => {
        if (pendingFocus.current !== request) return
        pendingFocus.current = null
        const panel = panels.current[next]
        if (panel?.isConnected && !panel.hidden) panel.focus()
      })
    }
  }

  // Accepted launches and explicit header actions reveal their destination. Background
  // snapshots never interrupt a chosen panel or discard in-progress selections.
  useEffect(() => {
    if (lastWorkspaceRequest.current === workspaceRequest) return
    lastWorkspaceRequest.current = workspaceRequest
    if (MODES.includes(workspaceRequest?.mode)) select(workspaceRequest.mode, { focusPanel: true })
  }, [workspaceRequest])

  const onKeyDown = (event, index) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? MODES.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + MODES.length) % MODES.length
    select(MODES[nextIndex])
    tabs.current[nextIndex]?.focus()
  }

  return <>
    <div className="rem-workspace-tabs" role="tablist" aria-label="Remediation workspace">
      {MODES.map((value, index) => <button key={value}
        ref={(node) => { tabs.current[index] = node }} type="button" role="tab"
        id={`rem-mode-${value}`} aria-controls={`rem-panel-${value}`} aria-selected={mode === value}
        tabIndex={mode === value ? 0 : -1} onKeyDown={(event) => onKeyDown(event, index)}
        onClick={() => select(value)}>
        {value === 'plan' ? 'Plan' : value === 'live' ? 'Live' : 'Review'}
        {value === 'review' && <span>{reviewCount.toLocaleString()}</span>}
        {value === 'live' && activeWork && <span className="rem-mode-live-dot" aria-label="active">●</span>}
      </button>)}
    </div>
    <div ref={node => { panels.current.plan = node }} id="rem-panel-plan" role="tabpanel" tabIndex={-1} aria-labelledby="rem-mode-plan"
      hidden={mode !== 'plan'}>{plan}</div>
    <div ref={node => { panels.current.review = node }} id="rem-panel-review" role="tabpanel" tabIndex={-1} aria-labelledby="rem-mode-review"
      hidden={mode !== 'review'}>{review}</div>
    <div ref={node => { panels.current.live = node }} id="rem-panel-live" role="tabpanel" tabIndex={-1} aria-labelledby="rem-mode-live"
      hidden={mode !== 'live'}>
      <h2 className="sr-only">Live Processing</h2>
      {live}
    </div>
  </>
}
