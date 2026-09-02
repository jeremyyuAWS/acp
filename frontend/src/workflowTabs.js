// WAI-ARIA tabs use one stop in the page's Tab order. Arrow keys move and activate within the
// set; disabled and role-gated tabs are skipped because they are absent from this local query.
export function handleWorkflowTabKeyDown(event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  const tabs = [...event.currentTarget.closest('[role="tablist"]')
    .querySelectorAll('[role="tab"]:not(:disabled)')]
  const current = tabs.indexOf(event.currentTarget)
  if (current < 0 || tabs.length === 0) return
  event.preventDefault()
  const target = event.key === 'Home' ? tabs[0]
    : event.key === 'End' ? tabs[tabs.length - 1]
      : tabs[(current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length]
  target.focus()
  target.click()
}
