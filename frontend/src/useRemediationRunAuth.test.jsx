import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'

const getRemediationSnapshot = vi.fn()
const close = vi.fn()
vi.mock('./api.js', () => ({
  getRemediationSnapshot: (...args) => getRemediationSnapshot(...args),
  openRemediationStream: vi.fn(() => ({ close })),
}))

const { useRemediationRun } = await import('./useRemediationRun.js')

function Harness() {
  useRemediationRun('scan-expired')
  return null
}

let host, root
beforeEach(async () => {
  vi.useFakeTimers()
  getRemediationSnapshot.mockReset().mockResolvedValue({ terminal: false, revision: 1 })
  close.mockReset()
  host = document.createElement('div')
  root = createRoot(host)
  await act(async () => { root.render(<Harness />) })
  await act(async () => { await Promise.resolve() })
})

afterEach(async () => {
  await act(async () => { root.unmount() })
  vi.useRealTimers()
})

describe('expired remediation sessions', () => {
  it('closes the stream and permanently stops fallback polling', async () => {
    expect(getRemediationSnapshot).toHaveBeenCalledTimes(1)

    await act(async () => {
      window.dispatchEvent(new CustomEvent('acp:session-expired'))
      await vi.advanceTimersByTimeAsync(20_000)
    })

    expect(close).toHaveBeenCalledTimes(1)
    expect(getRemediationSnapshot).toHaveBeenCalledTimes(1)
  })
})
