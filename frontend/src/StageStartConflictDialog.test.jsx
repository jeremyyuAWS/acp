// @vitest-environment jsdom
import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StageStartConflictDialog } from './StageStartConflictDialog.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('stage-start conflict integration', () => {
  let root
  let host

  afterEach(() => {
    if (root) act(() => root.unmount())
    host?.remove()
    root = null
    host = null
  })

  const renderConflict = (callbacks) => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    act(() => root.render(<StageStartConflictDialog
      choice={{ scanId: 'scan-remediate', activeStage: 'remediate' }} {...callbacks} />))
    return [...host.querySelectorAll('button')]
  }

  it('shows the dialog and routes the safe continuation to the existing workflow', () => {
    const onContinue = vi.fn()
    const onRestart = vi.fn()
    const onCancel = vi.fn()
    const buttons = renderConflict({ onContinue, onRestart, onCancel })

    expect(host.querySelector('[role="alertdialog"]')).toBeTruthy()
    expect(document.activeElement).toBe(buttons[0])
    act(() => buttons[0].click())
    expect(onContinue).toHaveBeenCalledOnce()
    expect(onRestart).not.toHaveBeenCalled()
  })

  it('routes explicit replacement and cancellation to the stage-start callbacks', () => {
    const onContinue = vi.fn()
    const onRestart = vi.fn()
    const onCancel = vi.fn()
    const buttons = renderConflict({ onContinue, onRestart, onCancel })

    act(() => buttons[1].click())
    expect(onRestart).toHaveBeenCalledOnce()
    expect(onContinue).not.toHaveBeenCalled()

    act(() => root.render(<StageStartConflictDialog
      choice={{ scanId: 'scan-release', activeStage: 'release' }}
      onContinue={onContinue} onRestart={onRestart} onCancel={onCancel} />))
    const cancel = [...host.querySelectorAll('button')].at(-1)
    act(() => cancel.click())
    expect(onCancel).toHaveBeenCalledOnce()
  })
})
