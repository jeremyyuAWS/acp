import { describe, it, expect, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// ADR 0019 — the escalation chip. A LOW-confidence finding that was sent to a cloud vision
// provider for a second opinion says so on the card; every other finding renders nothing.
//
// The persistence half is tests/test_issue_provenance_persistence.py — the chip can only be as
// truthful as the column feeding it, and the column is where the model's answer is dropped.

afterEach(unmountAll)

const { default: SecondOpinionChip, fmtCost } = await import('./SecondOpinionChip.jsx')

const HERE = dirname(fileURLToPath(import.meta.url))

const PROV = { provider: 'huggingface', zone: 'cloud', escalated: true, cost_usd: 0.00042 }

const render = async (props) => {
  const { container: c, root } = createTestRoot()
  await act(async () => { root.render(createElement(SecondOpinionChip, props)) })
  return c
}

describe('SecondOpinionChip (escalation provenance, ADR 0019)', () => {
  it('names the provider and marks the zone when a finding was escalated', async () => {
    const c = await render({ provenance: PROV })
    const chip = c.querySelector('.secondopinion')
    expect(chip).toBeTruthy()
    expect(chip.textContent).toContain('second opinion')
    expect(chip.textContent).toContain('huggingface')
    expect(chip.textContent).toContain('🟡')            // cloud, the same vocabulary as Settings
    expect(chip.getAttribute('data-zone')).toBe('cloud')
  })

  it('puts the cost in the title, not on the face of the card', async () => {
    const c = await render({ provenance: PROV })
    const chip = c.querySelector('.secondopinion')
    expect(chip.textContent).not.toContain('$')
    expect(chip.getAttribute('title')).toContain('$0.0004')
    expect(chip.getAttribute('title')).toContain('huggingface')
  })

  it('renders nothing for the un-escalated majority', async () => {
    for (const p of [undefined, null, {}, { escalated: false, provider: 'openai' }]) {
      const c = await render({ provenance: p })
      expect(c.querySelector('.secondopinion')).toBeNull()
    }
  })

  it('still renders when the provider reported no zone or no cost', async () => {
    // A partial record is a real possibility — the four fields come from a provider response
    // passing through handlers, and a missing one must degrade the chip, not blank it.
    const c = await render({ provenance: { escalated: true, provider: 'openai' } })
    const chip = c.querySelector('.secondopinion')
    expect(chip.textContent).toContain('openai')
    expect(chip.textContent).not.toContain('🟡')
    expect(chip.getAttribute('title')).not.toContain('$')
  })

  it('shows fractions of a cent rather than rounding a real charge to $0.00', () => {
    expect(fmtCost(0.00042)).toBe('$0.0004')
    expect(fmtCost(0)).toBe('$0.0000')
    expect(fmtCost(undefined)).toBeNull()
    expect(fmtCost('free')).toBeNull()
  })

  // ── the join, which is where the location chip was lost ────────────────────
  it('is mounted on the finding card, reading the key the store actually returns', () => {
    // FileDrawer's finding list is the surface a reviewer reads. Rendering the chip correctly in
    // isolation proves nothing if the card never mounts it, or mounts it from a key the API does
    // not send — the exact pair of true-on-their-own facts that lost the location chip
    // (tests/test_finding_location_reaches_the_card.py).
    const src = readFileSync(join(HERE, 'FileDrawer.jsx'), 'utf8')
    expect(src).toContain("import SecondOpinionChip from './SecondOpinionChip.jsx'")
    expect(src).toContain('<SecondOpinionChip provenance={i.hf_provenance} />')
  })
})
