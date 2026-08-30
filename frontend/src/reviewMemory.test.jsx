/**
 * ADR 0021 · Settings → Review Memory.
 *
 * The fixtures are the shapes `GET /org-memory` actually returns — `org_memory` rows, with the two
 * evidence payloads `api/memory.py:derive_org_memory` emits and no others — so these test the real
 * record rather than a convenient one.
 *
 * The assertions concentrate on the three ways this panel could mislead, in the order they would
 * do damage:
 *
 *   1. CLAIMING A RULE IS IN EFFECT WHEN IT IS NOT. ACP_REVIEW_MEMORY defaults OFF, and with it
 *      off `guidance_for` returns "" — an "active" rule shapes precisely nothing. A panel that
 *      renders status alone would tell an admin their house style is being applied when the
 *      prompt is byte-for-byte unchanged.
 *   2. OFFERING CONTROLS A USER CANNOT USE. Every write is _require_admin server-side. #952: a
 *      non-admin's click optimistically updated then silently reverted on the 403.
 *   3. DRESSING EVIDENCE UP. A derived proposal must show the counts its row carries and no
 *      adjective, percentage or confidence this panel invented.
 *
 * DOM-level, not browser-level: vite serves the SHARED checkout whatever worktree you are in
 * (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const getOrgMemory = vi.fn()
const addOrgMemoryRule = vi.fn()
const setOrgMemoryStatus = vi.fn()
const deriveOrgMemory = vi.fn()
vi.mock('./api.js', () => ({
  getOrgMemory: (...a) => getOrgMemory(...a),
  addOrgMemoryRule: (...a) => addOrgMemoryRule(...a),
  setOrgMemoryStatus: (...a) => setOrgMemoryStatus(...a),
  deriveOrgMemory: (...a) => deriveOrgMemory(...a),
}))

const { normalizeOrgMemory, normalizeRule, evidenceLine, AUTHORABLE_KINDS } =
  await import('./reviewMemory.js')
const ReviewMemory = (await import('./ReviewMemory.jsx')).default

afterEach(unmountAll)
beforeEach(() => {
  for (const m of [getOrgMemory, addOrgMemoryRule, setOrgMemoryStatus, deriveOrgMemory]) m.mockReset()
  getOrgMemory.mockResolvedValue({ rules: [], enabled: true })
  addOrgMemoryRule.mockResolvedValue({ id: 'n1', status: 'active' })
  setOrgMemoryStatus.mockResolvedValue({ id: 'r1', status: 'active' })
  deriveOrgMemory.mockResolvedValue({ proposed: [], count: 0 })
})

// Real row shapes. `evidence` arrives as a JSON STRING from the store, which is why the normalizer
// parses rather than reads it.
const authored = (over = {}) => ({
  id: 'a1', org: 'o@x', kind: 'style', rule_id: null, format: null,
  guidance: 'Keep alt text under 120 characters.', status: 'active',
  evidence: null, author: 'o@x', created_at: '2026-08-01T00:00:00Z', ...over,
})
const proposedShorten = (over = {}) => ({
  id: 'p1', org: 'o@x', kind: 'derived', rule_id: '1.1.1', format: null,
  guidance: 'Keep drafts concise — reviewers here shorten them.', status: 'proposed',
  evidence: JSON.stringify({ rule: '1.1.1', edited: 8, of: 10, median_delta_chars: -34,
                             window_days: 30 }),
  author: 'derivation', created_at: '2026-08-29T00:00:00Z', ...over,
})
const proposedVague = (over = {}) => ({
  id: 'p2', org: 'o@x', kind: 'derived', rule_id: '2.4.4', format: null,
  guidance: 'Be specific and descriptive — name what the content actually shows.',
  status: 'proposed',
  evidence: JSON.stringify({ rule: '2.4.4', rejected_too_vague: 6, of: 12, window_days: 30 }),
  author: 'derivation', created_at: '2026-08-29T00:00:00Z', ...over,
})

async function mount(props = { me: { is_admin: true } }) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ReviewMemory, props)) })
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
  return container
}

const text = (c) => c.textContent.replace(/\s+/g, ' ')

// ── 1. in effect vs merely "active" ──────────────────────────────────────────

describe('an active rule is not necessarily a rule in effect', () => {
  it('effective is false for every rule when the feature flag is off', () => {
    const m = normalizeOrgMemory({ enabled: false, rules: [authored(), authored({ id: 'a2' })] })
    expect(m.active).toHaveLength(2)
    expect(m.effectiveCount).toBe(0)
    expect(m.active.every((r) => r.effective === false)).toBe(true)
  })

  it('and true only for ACTIVE rules when it is on', () => {
    const m = normalizeOrgMemory({
      enabled: true, rules: [authored(), proposedShorten(), authored({ id: 'a3', status: 'archived' })],
    })
    expect(m.effectiveCount).toBe(1)
    expect(m.proposed[0].effective).toBe(false)
    expect(m.archived[0].effective).toBe(false)
  })

  it('the panel says so plainly rather than showing a green active list', async () => {
    getOrgMemory.mockResolvedValue({ enabled: false, rules: [authored()] })
    const c = await mount()
    expect(c.querySelector('.rm-disabled')).toBeTruthy()
    expect(text(c)).toMatch(/none of them is shaping any draft/i)
    // The rule is still listed and still editable — off is not hidden.
    expect(c.querySelectorAll('.rm-rule')).toHaveLength(1)
    expect(c.querySelector('.rm-rule .rm-effective')).toBeFalsy()
  })

  it('and leads with the real count when it is on', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [authored(), proposedShorten()] })
    const c = await mount()
    expect(c.querySelector('.rm-disabled')).toBeFalsy()
    expect(text(c)).toMatch(/1 rule is shaping drafts right now/i)
    expect(c.querySelectorAll('.rm-effective')).toHaveLength(1)  // only the active one
  })
})

// ── 2. admin gating ──────────────────────────────────────────────────────────

describe('write controls render only for an administrator', () => {
  it('a non-admin gets the rules read-only, and is told why', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [authored(), proposedShorten()] })
    const c = await mount({ me: { is_admin: false } })

    expect(c.querySelectorAll('.rm-rule')).toHaveLength(2)      // sees everything
    expect(c.querySelector('.rm-readonly')).toBeTruthy()
    expect(c.querySelector('.rm-author')).toBeFalsy()
    expect([...c.querySelectorAll('button')].map((b) => b.textContent)).toEqual([])
  })

  it('a missing me is treated as non-admin, not as admin', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [proposedShorten()] })
    const c = await mount({ me: null })
    expect(c.querySelector('.rm-readonly')).toBeTruthy()
    expect(text(c)).not.toMatch(/Accept/)
  })

  it('an admin gets accept/dismiss on a proposal and retire on an active rule', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [authored(), proposedShorten()] })
    const c = await mount()
    const labels = [...c.querySelectorAll('button')].map((b) => b.textContent)
    expect(labels).toContain('Accept')
    expect(labels).toContain('Dismiss')
    expect(labels).toContain('Retire')
  })
})

// ── 3. evidence is quoted, not characterised ─────────────────────────────────

describe('evidence', () => {
  it('renders the shorten signal as its real counts, with the sign preserved', () => {
    expect(evidenceLine(JSON.stringify({ edited: 8, of: 10, median_delta_chars: -34, window_days: 30 })))
      .toBe('Reviewers edited 8 of 10 drafts in the last 30 days — median 34 characters shorter.')
  })

  it('renders the too-vague signal as its real counts', () => {
    expect(evidenceLine(JSON.stringify({ rejected_too_vague: 6, of: 12, window_days: 30 })))
      .toBe('Reviewers rejected 6 of 12 drafts as too vague in the last 30 days.')
  })

  it('a positive delta is reported as LONGER, not as a shortening with a sign dropped', () => {
    expect(evidenceLine(JSON.stringify({ edited: 5, of: 5, median_delta_chars: 12 })))
      .toMatch(/12 characters longer/)
  })

  it('returns null for an unrecognised or unparseable shape rather than inventing one', () => {
    expect(evidenceLine(null)).toBeNull()
    expect(evidenceLine('')).toBeNull()
    expect(evidenceLine('not json')).toBeNull()
    expect(evidenceLine(JSON.stringify({ something_new: 3 }))).toBeNull()
  })

  it('and the panel distinguishes "no evidence" from "evidence we could not read"', async () => {
    getOrgMemory.mockResolvedValue({
      enabled: true, rules: [proposedShorten({ id: 'p9', evidence: '{{{ broken' })],
    })
    const c = await mount()
    expect(c.querySelector('.rm-evidence-missing')).toBeTruthy()
    expect(c.querySelector('.rm-evidence')).toBeFalsy()
  })

  it('states no percentage or confidence the panel computed', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [proposedShorten(), proposedVague()] })
    const c = await mount()
    const t = text(c)
    expect(t).toMatch(/Reviewers edited 8 of 10 drafts/)
    expect(t).not.toMatch(/%/)
    expect(t).not.toMatch(/confiden/i)
    expect(t).not.toMatch(/strong signal/i)
  })
})

// ── the writes ───────────────────────────────────────────────────────────────

describe('decisions reach the backend and refetch rather than optimistically rendering', () => {
  it('Accept sends status=active and re-reads the list', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [proposedShorten()] })
    const c = await mount()
    getOrgMemory.mockClear()

    const accept = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Accept')
    await act(async () => { accept.click() })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(setOrgMemoryStatus).toHaveBeenCalledWith('p1', 'active')
    expect(getOrgMemory, 'the backend is the authority on status — refetch, do not patch locally')
      .toHaveBeenCalled()
  })

  it('Dismiss archives rather than deleting — retired rules stay auditable', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [proposedShorten()] })
    const c = await mount()
    const dismiss = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Dismiss')
    await act(async () => { dismiss.click() })
    expect(setOrgMemoryStatus).toHaveBeenCalledWith('p1', 'archived')
  })

  it('a rejected write says an admin is required instead of failing silently', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [proposedShorten()] })
    setOrgMemoryStatus.mockRejectedValue(new Error('403'))
    const c = await mount()

    const accept = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Accept')
    await act(async () => { accept.click() })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(c.querySelector('.rm-error')).toBeTruthy()
    expect(text(c)).toMatch(/only an administrator/i)
  })

  it('an empty derivation run is reported as a real answer, not as a failure', async () => {
    deriveOrgMemory.mockResolvedValue({ proposed: [], count: 0 })
    const c = await mount()
    const btn = [...c.querySelectorAll('button')].find((b) => /Look for new proposals/.test(b.textContent))
    await act(async () => { btn.click() })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(c.querySelector('.rm-error')).toBeFalsy()
    expect(text(c)).toMatch(/not enough recent review signal/i)
  })
})

describe('authoring', () => {
  it('offers only the kinds the backend accepts', () => {
    // POST /org-memory 422s on anything outside {style, glossary}; `derived` is job-only, so
    // offering it would be offering a guaranteed failure.
    expect(AUTHORABLE_KINDS).toEqual(['style', 'glossary'])
    expect(AUTHORABLE_KINDS).not.toContain('derived')
  })

  it('sends the typed guidance and omits blank scope fields', async () => {
    const c = await mount()
    const ta = c.querySelector('textarea')
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set
      setter.call(ta, '  Prefer sentence case.  ')
      ta.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const form = c.querySelector('form.rm-author')
    await act(async () => { form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })) })
    await act(async () => { await Promise.resolve(); await Promise.resolve() })

    expect(addOrgMemoryRule).toHaveBeenCalledWith({
      kind: 'style', guidance: 'Prefer sentence case.', ruleId: null, format: null,
    })
  })
})

// ── the honest empty / error states ──────────────────────────────────────────

describe('empty and error states are different sentences', () => {
  it('a failed read says so, and does not claim the org has no house style', async () => {
    getOrgMemory.mockRejectedValue(new Error('network'))
    const c = await mount()
    expect(c.querySelector('.rm-error')).toBeTruthy()
    expect(text(c)).toMatch(/not a statement about your house style/i)
    expect(c.querySelector('.rm-empty')).toBeFalsy()
  })

  it('a genuinely empty org says that instead', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [] })
    const c = await mount()
    expect(c.querySelector('.rm-empty')).toBeTruthy()
    expect(c.querySelector('.rm-error')).toBeFalsy()
  })
})

describe('unscoped rules read as unscoped, not as missing data', () => {
  it('a NULL rule_id/format renders as "all criteria · all formats"', () => {
    const r = normalizeRule(authored(), { enabled: true })
    expect(r.ruleId).toBeNull()
    expect(r.format).toBeNull()
  })

  it('and the panel prints that rather than an empty cell', async () => {
    getOrgMemory.mockResolvedValue({ enabled: true, rules: [authored()] })
    const c = await mount()
    expect(text(c)).toMatch(/all criteria · all formats/)
  })
})

describe('the normalizer is total on junk', () => {
  it('never throws, whatever the body', () => {
    for (const junk of [null, undefined, {}, { rules: 'nope' }, { rules: [null] }]) {
      expect(() => normalizeOrgMemory(junk)).not.toThrow()
    }
    expect(normalizeOrgMemory(null).available).toBe(false)
    expect(normalizeOrgMemory({ rules: 'nope' }).active).toEqual([])
  })
})
