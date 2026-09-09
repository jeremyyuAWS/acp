import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import WaterfallRunNotice, { waterfallRunNotice, waterfallStageStatus } from './WaterfallRunNotice.jsx'
const now = Date.parse('2026-09-09T02:00:00Z')
const snapshot = { generated_at: '2026-09-09T01:59:55Z', state: 'running', documents: { processing: 2 } }
const notice = props => waterfallRunNotice({ snapshot, now, ...props })
describe('truthful waterfall run states', () => {
  it('distinguishes stale updates, missing history and disabled AI', () => {
    expect(notice({ snapshot: { ...snapshot, generated_at: '2026-09-09T01:58:00Z' } }).code).toBe('stale')
    expect(notice({ view: { available: false } }).detail).toContain('does not establish whether AI was used')
    expect(notice({ view: { available: true, ai_enabled: false } }).code).toBe('disabled')
    expect(notice({ error: true, view: { available: true } }).detail).toContain('last recorded')
  })
  it('distinguishes paused animation, queued work and processing', () => {
    expect(notice({ paused: true }).detail).toContain('does not stop remediation')
    expect(notice({ snapshot: { ...snapshot, documents: { waiting: 3 } } }).code).toBe('waiting')
    expect(notice({}).code).toBe('processing')
    expect(notice({ snapshot: { ...snapshot, documents: {} } }).code).toBe('unknown')
  })
  it('never equates terminal processing with all findings fixed', () => {
    expect(notice({ snapshot: { ...snapshot, terminal: true } }).detail).toContain('does not mean every finding was fixed')
    expect(notice({ snapshot: { ...snapshot, terminal: true, review: { items: 2 } } }).detail).toContain('Your review is still needed')
    expect(notice({ snapshot: { ...snapshot, terminal: true, documents: { failed: 1 } } }).code).toBe('failed')
  })
  it('does not mistake unknown charges for failed model outputs', () => {
    expect(notice({ view: { spending: { blocked: true } } }).detail).toContain('not evidence of a failed model response')
  })
  it('renders an accessible quiet notice', () => {
    const html = renderToStaticMarkup(<WaterfallRunNotice snapshot={snapshot} now={now} paused />)
    expect(html).toContain('role="status"')
    expect(html).toContain('data-waterfall-state="paused"')
  })
})
describe('recorded tier state labels', () => {
  it.each([
    [{ operations: 0 }, {}, 'Not used yet'],
    [{ operations: 0 }, { terminal: true }, 'Not used in this run'],
    [undefined, {}, 'Activity history unavailable'],
    [{ operations: 3 }, { aiEnabled: false }, 'AI disabled'],
    [{ active: 1 }, {}, 'Request dispatched'],
    [{ active: 1 }, { terminal: true }, 'Unsettled charge'],
    [{ reserved: 1 }, {}, 'waiting for dispatch'],
    [{ settled: 2 }, {}, 'Charge recorded'],
    [{ released: 2 }, {}, 'released without charge'],
    [{ uncertain: 1, settled: 2 }, {}, 'reconciliation'],
  ])('describes evidence without implying model success: %j %j', (stage, options, expected) => {
    expect(waterfallStageStatus(stage, options)).toContain(expected)
  })
})
