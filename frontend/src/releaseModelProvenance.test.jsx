// @vitest-environment jsdom
import { createElement, act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { aggregateReleaseModelCalls } from './ReleaseModelProvenance.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

vi.mock('./api.js', () => ({ getScanAiCalls: vi.fn(() => Promise.resolve([])) }))
afterEach(unmountAll)

describe('Release model provenance', () => {
  it('scopes calls to selected files and keeps exact provider/model/zone rows', () => {
    const rows = aggregateReleaseModelCalls([
      { file: 'a.docx', provider: 'openai', model: 'gpt-5', zone: 'customer_cloud', ok: 1, latency_ms: 100, cost_usd: 0.01 },
      { file: 'a.docx', provider: 'openai', model: 'gpt-5', zone: 'customer_cloud', ok: 0, latency_ms: 300, cost_usd: 0.02 },
      { file: 'b.docx', provider: 'ollama', model: 'llama3.1', zone: 'local', ok: 1, latency_ms: 50, cost_usd: 0 },
    ], ['a.docx'])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ provider: 'openai', model: 'gpt-5', zone: 'customer_cloud', calls: 2, succeeded: 1, failed: 1, averageLatencyMs: 200, costUsd: 0.03 })
  })

  it('does not turn call success into reviewer or validation evidence', async () => {
    const { default: ReleaseModelProvenance } = await import('./ReleaseModelProvenance.jsx')
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(ReleaseModelProvenance, { selectedFiles: [] })))
    expect(container.textContent).toContain('No model calls are recorded for the selected files.')
  })
})
