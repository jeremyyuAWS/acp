/**
 * ADR 0021 §E — the "house style applied" chip on the review card.
 *
 * Review memory rewrites the PROMPT behind a draft a human is about to certify. The ADR's
 * requirement is that this is never a hidden hand: the card says a draft was shaped, and the
 * statement expands to the exact guidance and — for a rule the org accepted from the derivation
 * job — the real count that justified it.
 *
 * The three ways this chip could lie, in the order they would do damage:
 *
 *   1. CLAIMING AN INFLUENCE THAT DID NOT HAPPEN. `ACP_REVIEW_MEMORY` defaults OFF, and off the
 *      backend attaches nothing because the prompt was byte-for-byte the pre-memory one. So a
 *      response with no `house_style` must produce NO chip — not an empty one, not a "0 rules"
 *      badge, which a reviewer would read as "checked, found none" when nothing was checked.
 *   2. SUMMARISING EVIDENCE INTO A CLAIM. A derived rule's counts are quoted (ADR 0016); this
 *      card computes no percentage, confidence or adjective from them.
 *   3. SHOWING A RULE THE PROMPT NEVER CARRIED. That one cannot be caught here — it is a
 *      backend property, held by tests/test_house_style_chip.py, where the chip's rows and the
 *      injected guidance are asserted to come from one selection.
 *
 * DOM-level, not browser-level: vite serves the SHARED checkout whatever worktree you are in
 * (CLAUDE.md), so a browser check would exercise a card without this change and pass.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const suggestFix = vi.fn()
vi.mock('./api.js', () => ({
  suggestFix: (...a) => suggestFix(...a),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

const { houseStyleFromDraft } = await import('./houseStyle.js')
const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

afterEach(unmountAll)

// The real `/ai/suggest` shapes. `evidence` arrives as a JSON STRING (the store holds it as one
// and the route passes it through untouched), which is why the normalizer parses rather than
// reads it.
const authored = (over = {}) => ({
  id: 'a1', kind: 'style', guidance: "Alt text: never begin with 'image of'.",
  rule_id: '1.1.1', format: null, evidence: null, ...over,
})
const orgWide = (over = {}) => ({
  id: 'a2', kind: 'style', guidance: 'Org-wide: British spelling.',
  rule_id: null, format: null, evidence: null, ...over,
})
const acceptedDerived = (over = {}) => ({
  id: 'd1', kind: 'derived', guidance: 'Keep drafts concise — reviewers here shorten them.',
  rule_id: '1.1.1', format: 'docx',
  evidence: JSON.stringify({ rule: '1.1.1', edited: 8, of: 10, median_delta_chars: -34,
                             window_days: 30 }),
  ...over,
})

const draft = (house) => ({
  suggestion: 'A clinician reviews a chart.', is_template: false, model: 'llava:7b',
  ...(house ? { house_style: house, house_style_applied: house.length } : {}),
})

// ── the normalizer ───────────────────────────────────────────────────────────────

describe('houseStyleFromDraft', () => {
  it('returns null when the draft was not shaped by memory', () => {
    // Every shape the flag-off / no-rules / older-backend path can produce.
    expect(houseStyleFromDraft(null)).toBeNull()
    expect(houseStyleFromDraft({ suggestion: 'x' })).toBeNull()
    expect(houseStyleFromDraft({ suggestion: 'x', house_style: [] })).toBeNull()
    // A bare count with no rules is NOT enough to draw a chip: there would be nothing to
    // expand, and the chip's entire value is being expandable.
    expect(houseStyleFromDraft({ suggestion: 'x', house_style_applied: 3 })).toBeNull()
  })

  it('reads the rules, their scope and their kind', () => {
    const hs = houseStyleFromDraft(draft([acceptedDerived(), authored(), orgWide()]))
    expect(hs.count).toBe(3)
    expect(hs.label).toBe('House style applied · 3 rules')
    expect(hs.rules.map((r) => r.kindLabel))
      .toEqual(['From your reviewers', 'House style', 'House style'])
    expect(hs.rules[0].ruleId).toBe('1.1.1')
    expect(hs.rules[0].format).toBe('docx')
    // Unscoped means "everywhere", and the panel and the card must say so the same way.
    expect(hs.rules[2].ruleId).toBeNull()
    expect(hs.rules[2].format).toBeNull()
  })

  it('singularises one rule', () => {
    expect(houseStyleFromDraft(draft([authored()])).label).toBe('House style applied · 1 rule')
  })

  it('preserves the backend order — the order the rules entered the prompt', () => {
    const hs = houseStyleFromDraft(draft([acceptedDerived(), authored(), orgWide()]))
    expect(hs.rules.map((r) => r.id)).toEqual(['d1', 'a1', 'a2'])
  })

  it('quotes a derived rule\'s real counts and invents nothing', () => {
    const hs = houseStyleFromDraft(draft([acceptedDerived()]))
    expect(hs.rules[0].evidence).toBe(
      'Reviewers edited 8 of 10 drafts in the last 30 days — median 34 characters shorter.')
    // No confidence, no percentage, no adjective anywhere in what this renders.
    const blob = JSON.stringify(hs)
    expect(blob).not.toMatch(/%|confidence|strong|likely|probably/i)
  })

  it('says when a derived rule\'s evidence could not be read, rather than showing a blank', () => {
    const hs = houseStyleFromDraft(draft([acceptedDerived({ evidence: '{not json' })]))
    expect(hs.rules[0].evidence).toBeNull()
    expect(hs.rules[0].evidenceMissing).toBe(true)
    // An AUTHORED rule has no evidence by design — that is not a defect and is not flagged.
    const authoredHs = houseStyleFromDraft(draft([authored()]))
    expect(authoredHs.rules[0].evidenceMissing).toBe(false)
  })

  it('drops a rule with no guidance text — it shaped nothing worth naming', () => {
    expect(houseStyleFromDraft(draft([authored({ guidance: '   ' })]))).toBeNull()
    const hs = houseStyleFromDraft(draft([authored({ guidance: '' }), orgWide()]))
    expect(hs.count).toBe(1)
    expect(hs.rules[0].id).toBe('a2')
  })
})

// ── the card ─────────────────────────────────────────────────────────────────────

const base = { id: 1, scan_id: 's1', file: 'handbook.docx', rule_id: '1.1.1',
               rule_name: 'Non-text Content', status: 'pending', finding_count: 1 }

let container, root
const mount = async (item = base) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {} })) })
}
const settle = async (n = 6) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const chip = () => container.querySelector('.evcard-house-style')

beforeEach(() => {
  suggestFix.mockReset()
  suggestFix.mockResolvedValue(draft([acceptedDerived(), authored(), orgWide()]))
})

describe('the review card renders the chip', () => {
  it('shows nothing at all when the draft carried no house style', async () => {
    suggestFix.mockResolvedValue(draft(null))
    await mount(); await settle()
    expect(chip(), 'a chip appeared for a draft memory never touched').toBeNull()
    expect(container.textContent).not.toMatch(/House style/)
  })

  it('names how many rules shaped the draft, and expands to each one', async () => {
    await mount(); await settle()
    const c = chip()
    expect(c, 'no house-style chip on a draft that was shaped by memory').toBeTruthy()
    expect(c.querySelector('summary').textContent).toContain('House style applied · 3 rules')
    // Expandable — a <details>, so the guidance is one disclosure away rather than a wall of
    // house rules on top of the value the reviewer is actually here to check.
    expect(c.tagName.toLowerCase()).toBe('details')
    const rules = [...c.querySelectorAll('.evcard-house-style-rule')]
    expect(rules).toHaveLength(3)
    expect(c.textContent).toContain("Alt text: never begin with 'image of'.")
    expect(c.textContent).toContain('Org-wide: British spelling.')
    // Scope is stated both ways round, so an unscoped rule doesn't read as missing data.
    expect(c.textContent).toContain('WCAG 1.1.1')
    expect(c.textContent).toContain('all criteria')
    expect(c.textContent).toContain('all formats')
  })

  it('shows a derived rule\'s evidence as the counts, with no invented confidence', async () => {
    await mount(); await settle()
    const ev = chip().querySelector('.evcard-house-style-evidence')
    expect(ev, 'an accepted derived rule showed no evidence').toBeTruthy()
    expect(ev.textContent).toContain('8 of 10 drafts')
    expect(ev.textContent).toContain('34 characters shorter')
    expect(chip().textContent).not.toMatch(/%|confidence/i)
    // The derived rule is marked as such — "your reviewers said this" is a different claim
    // from "an admin wrote this", and the reviewer weighs them differently.
    expect(chip().querySelector('[data-kind="derived"]')).toBeTruthy()
    expect(chip().textContent).toContain('From your reviewers')
  })

  it('says so when a derived rule\'s evidence is unreadable', async () => {
    suggestFix.mockResolvedValue(draft([acceptedDerived({ evidence: '{broken' })]))
    await mount(); await settle()
    expect(chip().querySelector('.evcard-house-style-evidence-missing')).toBeTruthy()
    expect(chip().querySelector('.evcard-house-style-evidence')).toBeNull()
  })

  it('drops the chip when a re-draft is no longer shaped by memory', async () => {
    // An admin retires the rule (or the flag goes off) between drafts. The chip must go with
    // it: a stale chip asserts an influence THIS draft did not have.
    //
    // The first draft is a TEMPLATE so the card offers "↻ Try again" — that button is the only
    // way to make a second single-box draft, and without it this test would silently exercise
    // nothing.
    suggestFix.mockResolvedValue({
      ...draft([authored()]), is_template: true, reason: 'Template only — no vision model.' })
    await mount(); await settle()
    expect(chip(), 'a template draft shaped by memory should still show the chip').toBeTruthy()

    const retry = [...container.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Try again'))
    expect(retry, 'no ↻ Try again button — the re-draft path was never exercised').toBeTruthy()
    suggestFix.mockResolvedValue(draft(null))
    await act(async () => { retry.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await settle()
    expect(chip(), 'the chip survived a draft that memory did not shape').toBeNull()
  })
})
