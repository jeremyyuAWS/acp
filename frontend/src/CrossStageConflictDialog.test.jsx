import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import axe from 'axe-core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CrossStageConflictDialog from './CrossStageConflictDialog.jsx'
import { STAGE_CONFLICT_DECISION } from './stageExecutionConflict.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('CrossStageConflictDialog', () => {
  let host
  let root
  let opener
  beforeEach(() => {
    opener = document.createElement('button')
    document.body.appendChild(opener)
    opener.focus()
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
  })
  afterEach(() => {
    act(() => root.unmount())
    host.remove(); opener.remove()
  })

  it('offers all three decisions and focuses the safe continuation choice', () => {
    act(() => root.render(<CrossStageConflictDialog
      conflict={{ currentExecutionId: 'exec-44', currentStage: 'remediate' }}
      requestedStage="assess" onDecision={() => {}} />))

    const dialog = host.querySelector('[role="alertdialog"]')
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.textContent).toContain('Continue Remediation')
    expect(dialog.textContent).toContain('Stop Remediation and start a new workflow revision')
    expect(dialog.textContent).toContain('Cancel')
    expect(document.activeElement.textContent).toBe('Continue Remediation')
  })

  it('cancels on Escape and restores focus when it closes', async () => {
    const onDecision = vi.fn()
    act(() => root.render(<CrossStageConflictDialog
      conflict={{ currentExecutionId: 'exec-44', currentStage: 'release' }}
      requestedStage="discover" onDecision={onDecision} />))
    act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(onDecision).toHaveBeenCalledWith(STAGE_CONFLICT_DECISION.CANCEL)
    act(() => root.render(<CrossStageConflictDialog conflict={null} onDecision={onDecision} />))
    await act(async () => {})
    expect(document.activeElement).toBe(opener)
  })

  it('keeps Tab focus inside the decision dialog', () => {
    act(() => root.render(<CrossStageConflictDialog
      conflict={{ currentExecutionId: 'exec-44', currentStage: 'release' }}
      requestedStage="discover" onDecision={() => {}} />))
    const buttons = host.querySelectorAll('button')
    buttons[2].focus()
    act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' })))
    expect(document.activeElement).toBe(buttons[0])
  })

  it('has no automatically detectable accessibility violations', async () => {
    act(() => root.render(<CrossStageConflictDialog
      conflict={{ currentExecutionId: 'exec-44', currentStage: 'release' }}
      requestedStage="discover" onDecision={() => {}} />))
    const result = await axe.run(host)
    expect(result.violations).toEqual([])
  })
})
