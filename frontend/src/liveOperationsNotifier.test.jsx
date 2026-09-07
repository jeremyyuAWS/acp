import React from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { LiveOperationsToast, newStageCompletions, newStageStarts, playNotificationSound } from './LiveOperationsNotifier.jsx'

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

  it('announces a completion only when an active stage becomes recent', () => {
    const active = { scan_id: 'one', stage: 'assess', status: 'active', running: 1, queued: 2 }
    const completed = { ...active, status: 'recent', running: 0, queued: 0, completed: 24, total: 24 }
    expect(newStageCompletions([active], [completed])).toEqual([completed])
    expect(newStageCompletions([], [completed])).toEqual([])
    expect(newStageCompletions([completed], [completed])).toEqual([])
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
    expect(markup).toContain('width:min(320px,calc(100vw - 28px))')
    expect(markup).toContain('padding:11px')
    expect(markup).toContain('border:1px solid var(--info-fg)')
    expect(markup).toContain('border-left:4px solid var(--info-fg)')
    expect(markup).toContain('background:var(--surface, #fff)')
    expect(markup).toContain('opacity:1')
    expect(markup).not.toContain('background:var(--panel)')
    expect(markup.match(/<button/g)).toHaveLength(2)
  })

  it('uses a distinct success treatment for stage completion', () => {
    const markup = renderToStaticMarkup(<LiveOperationsToast
      run={{ stage: 'discover', owner: 'admin@example.com', total: 9 }} kind="completed" />)
    expect(markup).toContain('Discovery complete')
    expect(markup).toContain('data-notification-kind="completed"')
    expect(markup).toContain('border:1px solid var(--success-fg)')
    expect(markup).toContain('border-left:4px solid var(--success-fg-strong)')
  })

  it('uses a distinct three-note completion chime', () => {
    vi.useFakeTimers()
    const frequencies = []
    const OriginalAudioContext = window.AudioContext
    window.AudioContext = class {
      currentTime = 0
      destination = {}
      createGain() { return { gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn() } }
      createOscillator() {
        const frequency = { value: 0 }
        frequencies.push(frequency)
        return { frequency, connect: vi.fn(), start: vi.fn(), stop: vi.fn() }
      }
      close() {}
    }
    playNotificationSound('completed')
    expect(frequencies.map((frequency) => frequency.value)).toEqual([523, 659, 784])
    window.AudioContext = OriginalAudioContext
    vi.runAllTimers()
    vi.useRealTimers()
  })
})
