import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { LiveOperationsToast, newStageStarts } from './LiveOperationsNotifier.jsx'

describe('Live Operations notifications', () => {
  it('announces only newly active Discover, Assess, and Remediate stages', () => {
    const previous = [{ scan_id: 'one', stage: 'discover', status: 'active', running: 1 }]
    const current = [
      ...previous,
      { scan_id: 'one', stage: 'assess', status: 'active', queued: 2 },
      { scan_id: 'two', stage: 'release', status: 'active', running: 1 },
      { scan_id: 'old', stage: 'remediate', status: 'recent', running: 0 },
    ]
    expect(newStageStarts(previous, current).map((run) => run.stage)).toEqual(['assess'])
  })

  it('opens Live Operations when the notification is clicked', () => {
    const onOpen = vi.fn()
    const run = { stage: 'remediate', owner: 'admin@example.com', total: 24 }
    const toast = LiveOperationsToast({ run, onOpen })
    const openButton = toast.props.children[1]
    openButton.props.onClick()
    expect(onOpen).toHaveBeenCalledOnce()
    const markup = renderToStaticMarkup(<LiveOperationsToast run={run} />)
    expect(markup).toContain('Remediation started')
    expect(markup).toContain('aria-atomic="true"')
    expect(markup).toContain('aria-label="Dismiss notification"')
    expect(markup).toContain('border:1px solid var(--success-fg)')
    expect(markup).toContain('border-left:5px solid var(--success-fg-strong)')
    expect(markup).toContain('background:var(--surface, #fff)')
    expect(markup).toContain('opacity:1')
    expect(markup).not.toContain('background:var(--panel)')
    expect(markup.match(/<button/g)).toHaveLength(2)
  })
})
