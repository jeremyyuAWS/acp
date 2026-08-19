import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { escalationPath } from './escalationPath.js'

// P1 item 2 — the auto-escalation numbered path. When the per-call ledger shows a local vision
// attempt that couldn't ground a description followed by an escalation to a cloud provider, the card
// shows the transparent path instead of surfacing the failed local attempt as a dead end. Everything
// is DERIVED from real ai_calls rows — nothing is fabricated.

describe('escalationPath — derived from the ledger only', () => {
  it('reads a local→cloud vision escalation off the rows', () => {
    const p = escalationPath([
      { surface: 'vision', zone: 'local', model: 'llava:13b', ok: true },
      { surface: 'vision', zone: 'cloud', provider: 'openai', model: 'gpt-4o', ok: true },
    ])
    expect(p).toEqual(expect.objectContaining({ provider: 'openai', cloudModel: 'gpt-4o', cloudOk: true }))
  })

  it('is null for an all-local ledger (the common case — no escalation to show)', () => {
    expect(escalationPath([{ surface: 'vision', zone: 'local', ok: true }])).toBeNull()
  })

  it('is null when there is no vision activity at all', () => {
    expect(escalationPath([{ surface: 'suggest', zone: 'local', ok: true }])).toBeNull()
    expect(escalationPath([])).toBeNull()
    expect(escalationPath(null)).toBeNull()
  })

  it('reports cloudOk=false honestly when the cloud escalation itself failed', () => {
    const p = escalationPath([
      { surface: 'vision', zone: 'local', ok: true },
      { surface: 'vision', zone: 'cloud', provider: 'anthropic', ok: false },
    ])
    expect(p.cloudOk).toBe(false)
    expect(p.provider).toBe('anthropic')
  })
})

// ── On the card ────────────────────────────────────────────────────────────────
const h = vi.hoisted(() => ({ calls: [] }))
vi.mock('./api.js', () => ({
  suggestFix: () => Promise.resolve({ suggestion: '', is_template: false }),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => ({ zone: 'cloud', provider: 'ollama', model: 'm', vision_model: 'v', host: 'h' }),
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve(h.calls),
  validateAlt: () => Promise.resolve({}),
}))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

// A 1.1.1 image finding with an AI-produced value (proposal) → provenance is meaningful and the
// escalation ledger is worth pulling.
const item = {
  id: 1, scan_id: 's1', file: 'deck.pptx', rule_id: '1.1.1', rule_name: 'Non-text Content',
  status: 'pending', finding_count: 1,
  proposals: [{ locator: 'ppt#img1', thumb: null, proposed_value: 'A bar chart of Q3 revenue by region',
                rationale: 'a stronger cloud vision model produced this after the local model could not ground it' }],
}

let container
const mount = async (props = {}) => {
  const { container: c, root } = createTestRoot()
  container = c
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {}, ...props })) })
  return c
}
afterEach(() => { h.calls = []; return unmountAll() })

describe('EvidenceCard — the escalation path on the card surface', () => {
  it('renders the transparent numbered path when the ledger shows a local→cloud escalation', async () => {
    h.calls = [
      { file: 'deck.pptx', surface: 'vision', zone: 'local', model: 'llava:13b', ok: true },
      { file: 'deck.pptx', surface: 'vision', zone: 'cloud', provider: 'openai', model: 'gpt-4o', ok: true },
    ]
    const c = await mount({ actualZone: 'cloud' })      // cloud-processed → proactive ledger fetch fires
    const path = c.querySelector('.evcard-escalation')
    expect(path).not.toBeNull()
    const t = path.textContent
    expect(t).toContain('local attempted')
    expect(t).toContain('no grounded description')
    expect(t).toContain('escalated to openai')
    expect(t).toContain('grounded')
    // it is on the card surface, not buried behind the audit disclosure
    expect(path.closest('details.evcard-details')).toBeNull()
  })

  it('shows nothing for an all-local ledger — the local attempt was not a dead end to explain', async () => {
    h.calls = [{ file: 'deck.pptx', surface: 'vision', zone: 'local', model: 'llava:13b', ok: true }]
    const c = await mount({ actualZone: 'cloud' })
    expect(c.querySelector('.evcard-escalation')).toBeNull()
  })
})
