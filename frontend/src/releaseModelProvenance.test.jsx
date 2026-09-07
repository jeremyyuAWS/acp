// @vitest-environment jsdom
import { createElement, act } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { aggregateReleaseModelCalls } from './ReleaseModelProvenance.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

const { getReleaseAiProvenance } = vi.hoisted(() => ({
  getReleaseAiProvenance: vi.fn(() => Promise.resolve([])),
}))
vi.mock('./api.js', () => ({ getReleaseAiProvenance }))
afterEach(unmountAll)

describe('Release model provenance', () => {
  it('scopes calls to selected files and keeps exact provider/model/zone rows', () => {
    const rows = aggregateReleaseModelCalls([
      { file: 'a.docx', provider: 'openai', model: 'gpt-5', zone: 'customer_cloud', ok: 1, latency_ms: 100, cost_usd: 0.01 },
      { file: 'a.docx', provider: 'openai', model: 'gpt-5', zone: 'customer_cloud', ok: 0, latency_ms: 300, cost_usd: 0.02 },
      { file: 'b.docx', provider: 'ollama', model: 'llama3.1', zone: 'local', ok: 1, latency_ms: 50, cost_usd: 0 },
    ].filter((row) => row.file === 'a.docx'))
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ provider: 'openai', model: 'gpt-5', zone: 'customer_cloud', calls: 2, succeeded: 1, failed: 1, averageLatencyMs: 200, costUsd: 0.03 })
  })

  it('keeps exact linked review and validation outcomes separate from call success', () => {
    const [row] = aggregateReleaseModelCalls([{ provider: 'openai', model: 'gpt-5', zone: 'cloud', ok: 1,
      review_decisions: [{ action: 'edit' }, { action: 'reject' }],
      validation_outcomes: [{ outcome: 'verified_regressed', regressions: ['2.4.4'] }] }])
    expect(row.review).toMatchObject({ approve: 0, edit: 1, reject: 1 })
    expect(row.validation.verified_regressed).toBe(1)
    expect(row.newlyFailing).toBe(1)
  })

  it('does not turn call success or missing linkage into reviewer or validation evidence', async () => {
    const { default: ReleaseModelProvenance } = await import('./ReleaseModelProvenance.jsx')
    const { container, root } = createTestRoot()
    getReleaseAiProvenance.mockResolvedValueOnce([{ provider: 'ollama', model: 'local', zone: 'local', ok: 1,
      latency_ms: 20, cost_usd: 0, review_decisions: [], validation_outcomes: [] }])
    await act(async () => root.render(createElement(ReleaseModelProvenance, { scanId: 's1', selectedFiles: ['a.docx'] })))
    expect(getReleaseAiProvenance).toHaveBeenCalledWith('s1', ['a.docx'])
    expect(container.textContent).toContain('Reviewer decisionsNot recorded for these calls')
    expect(container.textContent).toContain('Post-write validationNot recorded for these calls')
    expect(container.textContent).not.toContain('0 decisions')
  })

  it('renders accessible definitions for the three evidence groups', async () => {
    const { default: ReleaseModelProvenance } = await import('./ReleaseModelProvenance.jsx')
    const { container, root } = createTestRoot()
    getReleaseAiProvenance.mockResolvedValueOnce([{ provider: 'openai', model: 'gpt-5', zone: 'cloud', ok: 1,
      review_decisions: [{ action: 'approve' }], validation_outcomes: [{ outcome: 'verified_cleared', regressions: [] }] }])
    await act(async () => root.render(createElement(ReleaseModelProvenance, { scanId: 's1', selectedFiles: ['a.docx'] })))
    expect(container.querySelector('section').getAttribute('aria-labelledby')).toBe('release-ai-provenance-heading')
    expect([...container.querySelectorAll('dt')].map((node) => node.textContent)).toEqual(['Call operation', 'Reviewer decisions', 'Post-write validation'])
  })
})
