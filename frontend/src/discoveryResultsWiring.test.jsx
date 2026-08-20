/**
 * Discover mounts the Discovery results screen, and the acknowledgement GATES Assess.
 *
 * Two lanes, deliberately, because neither catches what the other does:
 *
 *   · SOURCE — a DOM test cannot see a call that was never made. If Discover stopped passing
 *     `scope.inventory`, or stopped rendering DiscoveryResults at all, a mount test over the
 *     component in isolation would still be green.
 *   · DOM — a source sweep cannot catch a syntax error, a stale prop name, or a gate that reads
 *     the wrong variable. The gate is exercised by clicking it.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const discover = read('Discover.jsx')
const results = read('DiscoveryResults.jsx')
const model = read('discoveryRecommendations.js')

describe('source — Discover is the caller, and it passes the real discovery data', () => {
  it('imports the screen and the acknowledgement model', () => {
    expect(discover).toMatch(/import DiscoveryResults from '\.\/DiscoveryResults\.jsx'/)
    expect(discover).toMatch(/import \{ acknowledgementSummary \} from '\.\/discoveryRecommendations\.js'/)
  })

  it('renders it with the discovered files, the stored inventory summary and the scope line', () => {
    expect(discover).toMatch(/<DiscoveryResults files=\{files\}/)
    // The inventory summary is what carries the whole-estate total and `truncated`; without it the
    // screen cannot tell a floor from a total.
    expect(discover).toMatch(/inventory=\{scope\?\.inventory \|\| null\}/)
    expect(discover).toMatch(/scopeLine=\{scopeLine\}/)
    expect(discover).toMatch(/acknowledged=\{ackRecs\} onAcknowledge=\{setAckRecs\}/)
    expect(discover).toMatch(/overrides=\{assessAnyway\} onOverridesChange=\{setAssessAnyway\}/)
  })

  it('gates the Assess button on the acknowledgement', () => {
    expect(discover).toMatch(/const recsToAck = acknowledgementSummary\(files, assessAnyway\)/)
    expect(discover).toMatch(/const needsAck = !!recsToAck && !ackRecs/)
    expect(discover).toMatch(/disabled=\{pendingActions > 0 \|\| needsAck\}/)
  })
})

describe('source — the screen adds no network call and the model stays pure', () => {
  it('DiscoveryResults derives everything from props — it does not fetch', () => {
    expect(results).not.toMatch(/from '\.\/api\.js'/)
    expect(results).not.toMatch(/\bfetch\(/)
  })

  it('the number model is React-free, so it is testable without a DOM', () => {
    expect(model).not.toMatch(/from 'react'/)
    expect(model).not.toMatch(/useState|useEffect/)
  })
})

// ── DOM ───────────────────────────────────────────────────────────────────────

const { default: Discover } = await import('./Discover.jsx')

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
afterEach(unmountAll)

const F = (file, extra = {}) => ({
  file, type: file.split('.').pop().toUpperCase(), tags: [], issues: [],
  department: 'Clinical', sourceName: 'SharePoint', ...extra,
})
const arch = (file) => F(file, {
  lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
  lifecycle_reason: "matched archive rule 'Legacy clinical policies'",
})

const render = async (files) => {
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [{ name: 'SharePoint' }], files, busy: false, onScan: () => {},
      onAdvance: () => {},
    }))
  })
  return container
}
const assessBtn = () => [...container.querySelectorAll('button')]
  .find((b) => b.textContent.includes('Assess — score vs WCAG'))
const byText = (t) => [...container.querySelectorAll('button, label')]
  .find((el) => el.textContent.includes(t))
const click = async (el) => { await act(async () => { el.click() }) }

describe('DOM — the acknowledgement gates Assess on the Discover tab', () => {
  it('mounts the Discovery results screen inside Discover', async () => {
    await render([arch('Clinical/old-pathway.docx'), F('Clinical/live.docx', { lifecycle_status: 'Active' })])
    expect(container.textContent).toContain('DISCOVERY RESULTS')
    expect(container.textContent).toContain('tagged for archive review')
    expect(container.textContent).toContain('Legacy clinical policies')
  })

  it('blocks Assess until the recommendations are approved, then releases it', async () => {
    await render([arch('Clinical/old-pathway.docx'), F('Clinical/live.docx', { lifecycle_status: 'Active' })])
    // Accept the per-row lifecycle decisions first, so the ONLY thing left holding the button is
    // the acknowledgement — otherwise this would pass for the pre-existing pending-actions reason.
    await click(byText('Accept all recommendations'))
    expect(assessBtn().disabled).toBe(true)
    expect(container.textContent).toContain('Approve the 1 discovery recommendation above to continue')

    await click(byText('I approve these 1 recommendation.').querySelector('input'))
    expect(assessBtn().disabled).toBe(false)
  })

  it('leaves the button alone when there is nothing to acknowledge', async () => {
    // No lifecycle column on any row — the recommendation surface is absent, so it cannot gate.
    await render([F('Clinical/live.docx')])
    await click(byText('Accept all recommendations'))
    expect(container.textContent).not.toContain('to continue')
    expect(assessBtn().disabled).toBe(false)
  })
})
