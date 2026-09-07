// Monitor's recent-job rows must keep machine job types out of the filename column.
// The production defect was visible as `apply_approved_values` painted directly over a
// document name because the type had no label and its 82px grid track did not clip.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement, act } from 'react'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getJobs = vi.fn()
vi.mock('./api.js', () => ({
  getJobs: (...args) => getJobs(...args),
  setWorkers: vi.fn(), clearDeadJobs: vi.fn(), getWorkerReplicas: vi.fn(),
  getWorkerCapacity: vi.fn(),
}))
vi.mock('./Transparency.jsx', () => ({ TraceChip: () => createElement('span', null, 'trace') }))

import { resetJobsFeed } from './jobsFeed.js'
const { default: QueuePanel } = await import('./QueuePanel.jsx')

beforeEach(() => resetJobsFeed())
afterEach(async () => { await unmountAll(); getJobs.mockReset() })

const settle = async () => {
  for (let i = 0; i < 4; i += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
}

describe('QueuePanel recent-job row layout', () => {
  it('renders approval work with a short label and preserves the exact type as its title', async () => {
    const now = new Date().toISOString()
    getJobs.mockResolvedValue({
      workers: 1, worker_tier_alive: true, runtime_mode: 'worker', stats: { done: 1 },
      jobs: [{
        id: 'j1', type: 'apply_approved_values', status: 'done', scan_id: 's1',
        payload: JSON.stringify({ file: 'Metabolic Panel Log - Devon Stand-in.xlsx' }),
        created_at: now, updated_at: now, attempts: 1,
      }],
    })
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(QueuePanel)))
    await settle()

    const type = container.querySelector('.jobtype')
    expect(type.textContent).toBe('apply approval')
    expect(type.title).toBe('apply_approved_values')
    expect(container.querySelector('.jobfile').textContent).toContain('Metabolic Panel Log')
  })

  it('constrains both text tracks and moves the filename to its own responsive row', () => {
    const here = dirname(fileURLToPath(import.meta.url))
    const css = readFileSync(join(here, 'styles.css'), 'utf8')
    expect(css).toMatch(/\.jobtype \{[^}]*min-width: 0[^}]*overflow: hidden[^}]*text-overflow: ellipsis/)
    expect(css).toMatch(/@media \(max-width: 900px\)[^]*\.jobfile \{[^}]*grid-column: 1 \/ -1[^}]*grid-row: 2/)
  })
})
