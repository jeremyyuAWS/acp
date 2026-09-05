/**
 * ADR 0021 §E — the house-style chip on a card pre-drafted at SCAN time.
 *
 * #999 shipped the chip for drafts from the live /ai/suggest path. A card whose value arrived
 * pre-drafted during the scan showed nothing, because handlers._propose_text_findings injected
 * house style into those prompts and recorded nowhere which rules it used. The scan now stamps
 * them onto each proposal, and the card reads them through the SAME normalizer the live path
 * uses — one chip, two sources.
 *
 * WHAT MUST NOT HAPPEN, and why most of these tests are about absence: only five criteria are
 * handed guidance at scan time. The rest are deterministic proposers ADR 0021 excludes by name
 * ("there is nothing to steer"), and their cards must render no chip at all. A chip there would
 * claim an influence that never happened, on a value a human is about to certify — the exact
 * failure the chip was built to prevent. The backend half of that guarantee is pinned in
 * tests/test_proposal_house_style.py; this is the render half.
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
  getSourceLink: () => Promise.resolve({ url: null }),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

const { houseStyleOf } = await import('./reviewCard.js')
const { default: EvidenceCard } = await import('./EvidenceCard.jsx')

afterEach(unmountAll)

const AUTHORED = {
  id: 'r1', kind: 'style', guidance: 'Link text: lead with the verb.',
  rule_id: '2.4.4', format: null, evidence: null,
}
const DERIVED = {
  id: 'd1', kind: 'derived', guidance: 'Keep drafts concise — reviewers here shorten them.',
  rule_id: '2.4.4', format: 'docx',
  evidence: JSON.stringify({ rule: '2.4.4', edited: 8, of: 10, median_delta_chars: -34,
                             window_days: 30 }),
}

const proposal = (over = {}) => ({
  locator: 'l1', before: 'click here', proposed_value: 'Read the policy', ...over,
})

// ── the selector ─────────────────────────────────────────────────────────────────

describe('houseStyleOf', () => {
  it('reads the rules off a stamped proposal', () => {
    expect(houseStyleOf({ proposals: [proposal({ house_style: [AUTHORED] })] }))
      .toEqual([AUTHORED])
  })

  it('returns null for a card the scan did not stamp', () => {
    // The common case by a wide margin — every deterministic criterion, and every card at all
    // when ACP_REVIEW_MEMORY is off.
    expect(houseStyleOf({ proposals: [proposal()] })).toBeNull()
    expect(houseStyleOf({ proposals: [] })).toBeNull()
    expect(houseStyleOf({})).toBeNull()
    expect(houseStyleOf(null)).toBeNull()
  })

  it('treats an empty list as no house style', () => {
    // A chip with nothing in it is worse than no chip: it says "memory applied" and then cannot
    // say what.
    expect(houseStyleOf({ proposals: [proposal({ house_style: [] })] })).toBeNull()
  })

  it('does not depend on the stamp being first', () => {
    // The value is card-level, so any proposal answers for the card. Scanning rather than reading
    // index 0 keeps the chip independent of list order, which nothing else guarantees.
    expect(houseStyleOf({
      proposals: [proposal(), proposal({ locator: 'l2', house_style: [AUTHORED] })],
    })).toEqual([AUTHORED])
  })

  it('ignores a malformed stamp rather than throwing', () => {
    expect(houseStyleOf({ proposals: [proposal({ house_style: 'not-a-list' })] })).toBeNull()
  })
})

// ── the card ─────────────────────────────────────────────────────────────────────

const base = { id: 1, scan_id: 's1', file: 'handbook.docx', rule_id: '2.4.4',
               rule_name: 'Link Purpose (In Context)', status: 'pending', finding_count: 1 }

let container, root
const mount = async (item) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {} })) })
}
const settle = async (n = 6) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const chip = () => container.querySelector('.evcard-house-style')

beforeEach(() => {
  suggestFix.mockReset()
  // A card that already carries a proposal does not auto-draft, so no live call happens — which
  // is the whole point: this is the scan-time path.
  suggestFix.mockResolvedValue({ suggestion: '', is_template: false })
})

describe('a scan-time pre-drafted card', () => {
  it('shows the chip for the rules the scan actually injected', async () => {
    await mount({ ...base, proposals: [proposal({ house_style: [AUTHORED] })] })
    await settle()
    const c = chip()
    expect(c, 'no chip on a pre-drafted card whose prompt carried house style').toBeTruthy()
    expect(c.textContent).toContain('House style applied · 1 rule')
    expect(c.textContent).toContain('Link text: lead with the verb.')
    expect(suggestFix).not.toHaveBeenCalled()   // no live draft — this came from the scan
  })

  it('shows a derived rule\'s real counts, same as the live path', async () => {
    await mount({ ...base, proposals: [proposal({ house_style: [DERIVED, AUTHORED] })] })
    await settle()
    expect(chip().textContent).toContain('House style applied · 2 rules')
    const ev = chip().querySelector('.evcard-house-style-evidence')
    expect(ev, 'the derived rule showed no evidence').toBeTruthy()
    expect(ev.textContent).toContain('8 of 10 drafts')
    expect(chip().textContent).not.toMatch(/%|confidence/i)
  })

  it('shows NOTHING for a deterministic criterion the scan did not stamp', async () => {
    // 1.3.2 reading order is deterministic — ADR 0021 excludes it from memory entirely. This is
    // the assertion that matters: a chip here would be a fabricated claim.
    await mount({ ...base, rule_id: '1.3.2', rule_name: 'Meaningful Sequence',
                  proposals: [proposal()] })
    await settle()
    expect(chip(), 'a chip appeared on a draft memory never shaped').toBeNull()
    expect(container.textContent).not.toMatch(/House style/)
  })

  it('shows nothing when the stamp is an empty list', async () => {
    await mount({ ...base, proposals: [proposal({ house_style: [] })] })
    await settle()
    expect(chip()).toBeNull()
  })
})
