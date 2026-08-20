/**
 * R10 · Audit trail — what was changed, by whom or by what, and when.
 *
 * The fixtures below are the shapes `store.document_timeline` actually emits, kind by kind, so these
 * tests are about the real record rather than about a convenient one. The assertions concentrate on
 * the one place an audit surface can lie without anybody noticing: attribution. A trail that fills
 * an empty "who" column with a plausible name is worse than one that leaves it blank, and the
 * backend leaves it blank on five of its eight event kinds.
 *
 * DOM-level, not browser-level: vite serves the SHARED checkout whatever worktree you are in
 * (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const getDocumentTimeline = vi.fn()
vi.mock('./api.js', () => ({ getDocumentTimeline: (...a) => getDocumentTimeline(...a) }))

const { auditEvent, auditTrail, auditSummary, stamp, KINDS } = await import('./documentAudit.js')
const DocumentAudit = (await import('./DocumentAudit.jsx')).default

afterEach(unmountAll)
beforeEach(() => { getDocumentTimeline.mockReset(); getDocumentTimeline.mockResolvedValue([]) })

// The eight kinds as document_timeline builds them, with the actor column it actually sets.
const EV = {
  scan:    { ts: '2026-08-20T09:00:00Z', kind: 'scan',    title: 'Scan started (drive)', actor: null },
  ai:      { ts: '2026-08-20T09:01:00Z', kind: 'ai',      title: 'AI vision · ollama llava:13b',
             detail: 'zone=local · ok', actor: null },
  review:  { ts: '2026-08-20T09:02:00Z', kind: 'review',  title: 'Queued for human review · 1.1.1',
             detail: 'Non-text Content', rule_id: '1.1.1', actor: null },
  human:   { ts: '2026-08-20T09:03:00Z', kind: 'human',   title: 'Human approve · 1.1.1',
             detail: 'reviewer edited the AI draft before approving', rule_id: '1.1.1',
             actor: 'dana@example.com' },
  fix:     { ts: '2026-08-20T09:04:00Z', kind: 'fix',     title: 'Fix written into document · 1.1.1',
             detail: 'A bar chart of quarterly revenue', rule_id: '1.1.1', actor: null },
  publish: { ts: '2026-08-20T09:05:00Z', kind: 'publish', title: 'Published',
             detail: 'https://drive.example/x', actor: null },
  // log_decision("system", …) — the pipeline's own rows. "system" is the ABSENCE of a person.
  decision: { ts: '2026-08-20T09:06:00Z', kind: 'decision', title: 'remediate.applied',
              detail: 'set document title', actor: 'system' },
  certify: { ts: '2026-08-20T09:07:00Z', kind: 'certify', title: 'Certified conformant', actor: 'system' },
}

async function mount(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(DocumentAudit, props)) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return container
}

// ── attribution ─────────────────────────────────────────────────────────────
describe('by whom, or by what — and which of the two the record actually said', () => {
  it('a named reviewer is reported as recorded', () => {
    const r = auditEvent(EV.human)
    expect(r.by).toBe('dana@example.com')
    expect(r.attribution).toBe('recorded')
  })

  it('"system" is the absence of a person, not the name of one', () => {
    // Both of these carry an actor column, and neither carries a human.
    expect(auditEvent(EV.decision).by).toBe('ACP')
    expect(auditEvent(EV.decision).attribution).toBe('derived')
    expect(auditEvent(EV.certify).by).toBe('ACP')
    expect(auditEvent(EV.certify).attribution).toBe('derived')
  })

  it('kinds with no actor column at all are attributed to the automation, marked derived', () => {
    expect(auditEvent(EV.scan)).toMatchObject({ by: 'ACP scan pipeline', attribution: 'derived' })
    expect(auditEvent(EV.fix)).toMatchObject({ by: 'ACP remediation worker', attribution: 'derived' })
    expect(auditEvent(EV.publish)).toMatchObject({ by: 'ACP publish step', attribution: 'derived' })
    expect(auditEvent(EV.review)).toMatchObject({ by: 'ACP (routing)', attribution: 'derived' })
  })

  it('an AI call names its real model, off the persisted title', () => {
    const r = auditEvent(EV.ai)
    expect(r.by).toBe('ollama llava:13b')
    expect(r.attribution).toBe('recorded')
    // a title without the provider/model tail falls back rather than slicing something arbitrary
    expect(auditEvent({ ...EV.ai, title: 'AI call' }).by).toBe('an AI model')
    expect(auditEvent({ ...EV.ai, title: 'AI call' }).attribution).toBe('derived')
  })

  it('a human decision with no reviewer recorded says so instead of guessing', () => {
    const r = auditEvent({ ...EV.human, actor: null })
    expect(r.by).toBe('a reviewer (not named in the record)')
    expect(r.attribution).toBe('derived')
  })
})

// ── what was changed ────────────────────────────────────────────────────────
describe('only the events that changed the document are marked as changes', () => {
  it('a fix and a publish change it; a scan, an AI call, a routing and a verdict do not', () => {
    expect(auditEvent(EV.fix).changed).toBe(true)
    expect(auditEvent(EV.publish).changed).toBe(true)
    for (const k of ['scan', 'ai', 'review', 'human', 'decision', 'certify']) {
      expect(auditEvent(EV[k]).changed).toBe(false)
    }
  })
})

// ── the trail ───────────────────────────────────────────────────────────────
describe('auditTrail and auditSummary', () => {
  it('orders oldest first and drops events with no timestamp', () => {
    const rows = auditTrail([EV.publish, EV.scan, { kind: 'fix', title: 'no ts' }, EV.fix])
    expect(rows.map((r) => r.kind)).toEqual(['scan', 'fix', 'publish'])
  })

  it('a non-array is null — an unloaded trail is not an empty one', () => {
    expect(auditTrail(null)).toBe(null)
    expect(auditTrail(undefined)).toBe(null)
    expect(auditTrail([])).toEqual([])          // [] IS the claim, once something answered
  })

  it('counts named people, not human-kind events', () => {
    const s = auditSummary(auditTrail(Object.values(EV)))
    expect(s.events).toBe(8)
    expect(s.changes).toBe(2)
    expect(s.people).toBe(1)
    expect(s.peopleNames).toEqual(['dana@example.com'])
    // the AI model is a recorded attribution but is not a person, so it is not counted here
    const noPeople = auditSummary(auditTrail([EV.ai, EV.fix, EV.scan]))
    expect(noPeople.people).toBe(0)
  })

  it('stamps absolutely, never relatively — a trail is read later', () => {
    expect(stamp('2026-08-20T09:04:00Z')).toBe('2026-08-20 09:04:00Z')
    expect(stamp('not a date')).toBe('not a date')
  })

  it('an unknown kind is not dropped', () => {
    const r = auditEvent({ ts: '2026-08-20T09:00:00Z', kind: 'something_new', title: 'x' })
    expect(r).toBeTruthy()
    expect(KINDS.includes(r.kind)).toBe(true)
  })
})

// ── rendering ───────────────────────────────────────────────────────────────
describe('DocumentAudit rendering', () => {
  it('renders nothing before the fetch answers', async () => {
    let resolve
    getDocumentTimeline.mockReturnValue(new Promise((r) => { resolve = r }))
    const c = await mount({ scanId: 's1', file: 'a.docx' })
    expect(c.textContent).toBe('')
    await act(async () => { resolve([]) })
  })

  it('an empty trail says what it does and does not establish', async () => {
    getDocumentTimeline.mockResolvedValue([])
    const c = await mount({ scanId: 's1', file: 'a.docx' })
    const empty = c.querySelector('.audit-empty').textContent
    expect(empty).toMatch(/No events are recorded/)
    expect(empty).toMatch(/not evidence that nothing happened/)
  })

  it('shows when, what, and by whom for each event, oldest first', async () => {
    getDocumentTimeline.mockResolvedValue([EV.human, EV.scan, EV.fix])
    const c = await mount({ scanId: 's1', file: 'a.docx' })
    const rows = [...c.querySelectorAll('.audit-row')]
    expect(rows.map((r) => r.getAttribute('data-kind'))).toEqual(['scan', 'human', 'fix'])
    expect(rows[0].querySelector('.audit-when').textContent).toBe('2026-08-20 09:00:00Z')
    expect(rows[1].textContent).toMatch(/dana@example\.com/)
    expect(rows[2].textContent).toMatch(/A bar chart of quarterly revenue/)
  })

  /**
   * Scoped to the one row's `by` cell, deliberately. The section's own explanatory copy says that
   * the record names no actor for most events — a section-wide assertion about that phrase would
   * match the explanation rather than the claim, which is the shape that has failed twice here.
   */
  it('a derived attribution is marked on its own row, and a recorded one is not', async () => {
    getDocumentTimeline.mockResolvedValue([EV.human, EV.fix])
    const c = await mount({ scanId: 's1', file: 'a.docx' })
    const by = (kind) => c.querySelector(`.audit-row[data-kind="${kind}"] .audit-by`)
    expect(by('human').querySelector('.audit-recorded')).toBeTruthy()
    expect(by('human').querySelector('.audit-derived')).toBeNull()
    expect(by('fix').querySelector('.audit-derived')).toBeTruthy()
    expect(by('fix').querySelector('.audit-recorded')).toBeNull()
  })

  it('the summary names the people the log named, and says so when it named none', async () => {
    getDocumentTimeline.mockResolvedValue([EV.human, EV.fix])
    const withPerson = await mount({ scanId: 's1', file: 'a.docx' })
    expect(withPerson.querySelector('.audit-summary').textContent)
      .toMatch(/names one person: dana@example\.com/)

    getDocumentTimeline.mockResolvedValue([EV.scan, EV.fix])
    const without = await mount({ scanId: 's1', file: 'b.docx' })
    expect(without.querySelector('.audit-summary').textContent)
      .toMatch(/names no person on any of these events/)
  })

  it('never claims to hold the value a change replaced', async () => {
    getDocumentTimeline.mockResolvedValue([EV.fix])
    const c = await mount({ scanId: 's1', file: 'a.docx' })
    expect(c.textContent).toMatch(/does not record what that value replaced/)
  })

  it('changes-only filters to the events that wrote something', async () => {
    getDocumentTimeline.mockResolvedValue(Object.values(EV))
    const c = await mount({ scanId: 's1', file: 'a.docx', changesOnly: true })
    expect([...c.querySelectorAll('.audit-row')].map((r) => r.getAttribute('data-kind')))
      .toEqual(['fix', 'publish'])
    const box = c.querySelector('input[type="checkbox"]')
    await act(async () => { box.click() })
    expect(c.querySelectorAll('.audit-row').length).toBe(8)
  })

  it('a trail that changed nothing says that, rather than showing an empty list', async () => {
    getDocumentTimeline.mockResolvedValue([EV.scan, EV.ai])
    const c = await mount({ scanId: 's1', file: 'a.docx', changesOnly: true })
    expect(c.querySelector('.audit-nochanges').textContent).toMatch(/Nothing in this trail changed/)
  })
})
