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
const loader = read('discoveryInventory.js')
const api = read('api.js')

describe('source — Discover is the caller, and it passes the real discovery data', () => {
  it('imports the screen and the acknowledgement model', () => {
    expect(discover).toMatch(/import DiscoveryResults from '\.\/DiscoveryResults\.jsx'/)
    expect(discover).toMatch(/import \{ acknowledgementSummary \} from '\.\/discoveryRecommendations\.js'/)
  })

  it('renders it with the merged file rows, the stored inventory summary and the scope line', () => {
    // `estateFiles`, not `files`: the lifecycle columns are merged in from the inventory read, and
    // passing the raw rows would leave the recommendation surface permanently absent.
    expect(discover).toMatch(/<DiscoveryResults files=\{estateFiles\}/)
    // The inventory summary is what carries the whole-estate total and `truncated`; without it the
    // screen cannot tell a floor from a total.
    expect(discover).toMatch(/inventory=\{scope\?\.inventory \|\| null\}/)
    expect(discover).toMatch(/scopeLine=\{scopeLine\}/)
    expect(discover).toMatch(/acknowledged=\{ackRecs\} onAcknowledge=\{setAckRecs\}/)
    expect(discover).toMatch(/overrides=\{assessAnyway\} onOverridesChange=\{setAssessAnyway\}/)
    // Lifecycle rules #8 — a real handler, not a stub: wired to the same reload path every other
    // scan_inventory mutation would need, so the recorded override actually reaches this screen.
    expect(discover).toMatch(/onOverrideRecommendation=\{overrideRecommendation\}/)
  })

  it('overrideRecommendation POSTs the override then reloads the inventory, never patches state locally', () => {
    expect(discover).toMatch(/const overrideRecommendation = useCallback\(async \(file, reason\) => \{/)
    expect(discover).toMatch(/await overrideLifecycleRecommendation\(scanId, file, reason\)/)
    expect(discover).toMatch(/reloadInventory\(\)/)
  })

  it('gates the Assess button on the acknowledgement', () => {
    expect(discover).toMatch(/const recsToAck = acknowledgementSummary\(estateFiles, assessAnyway\)/)
    expect(discover).toMatch(/const needsAck = !!recsToAck && !ackRecs/)
    expect(discover).toMatch(/disabled=\{pendingActions > 0 \|\| needsAck\}/)
  })
})

describe('source — the lifecycle columns are read from the route that actually has them', () => {
  it('api.js exports a helper for GET /scans/{id}/inventory, paginated', () => {
    expect(api).toMatch(/export const getScanInventory = \(scanId, \{ offset = 0, limit = 1000 \} = \{\}\) =>/)
    expect(api).toMatch(/\/inventory\?offset=\$\{offset\}&limit=\$\{limit\}/)
    // Same auth the rest of the module uses — a helper that dropped headers() would 401 silently.
    expect(api).toMatch(/inventory\?offset[\s\S]{0,120}headers\(\)/)
    // And a SIM branch, like every neighbouring scan read.
    expect(api).toMatch(/SIM\s*\n?\s*\? sim\(simScanInventory\(scanId, offset, limit\)/)
  })

  it('Discover reads it through the complete-or-nothing loader', () => {
    expect(discover).toMatch(/import \{ loadDiscoveryInventory, mergeLifecycle \} from '\.\/discoveryInventory\.js'/)
    // Named import, not the whole import LINE: the line grew a second name when the unreadable
    // breakdown started reading the scan's decision log, and pinning the line made a correct
    // addition fail. What matters here is that this reader comes from api.js.
    expect(discover).toMatch(/import \{[^}]*\bgetScanInventory\b[^}]*\} from '\.\/api\.js'/)
    expect(discover).toMatch(/loadDiscoveryInventory\(scanId, getScanInventory\)/)
    // Keyed on the scan, and reset the instant the id changes — a stale read attributed to a new
    // scan would be a wrong answer rather than a missing one.
    expect(discover).toMatch(/setInv\(null\)/)
    expect(discover).toMatch(/\}, \[scanId\]\)/)
    expect(discover).toMatch(/mergeLifecycle\(files, inv\)/)
  })

  it('the loader is fetch-injected and React-free, so the failure path is testable', () => {
    expect(loader).not.toMatch(/from 'react'/)
    expect(loader).not.toMatch(/from '\.\/api\.js'/)
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
// By the stable hook rather than the label — these cases are about the acknowledgement GATE.
const assessBtn = () => container.querySelector('button[data-advance="assess"]')
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
    // Both rows here carry a REAL lifecycle_status (one archive, one a rule pass that measured
    // Keep), so both are acceptable and the bulk button names them: "Accept all 2 recommendations".
    await click(byText('Accept all 2 recommendations'))
    expect(assessBtn().disabled).toBe(true)
    expect(container.textContent).toContain('Approve the 1 discovery recommendation above to continue')

    await click(byText('I approve these 1 recommendation.').querySelector('input'))
    expect(assessBtn().disabled).toBe(false)
  })

  it('leaves the button alone when there is nothing to acknowledge', async () => {
    // No lifecycle column on any row — the recommendation surface is absent, so it cannot gate.
    //
    // Nothing to ACCEPT either, for the same underlying reason: with no lifecycle_status and no
    // age/usage signal, retentionSignal calls this row 'unassessed', which is not a recommendation
    // a bulk action can accept — so the "Accept all" button does not render at all rather than
    // rubber-stamping a fabricated Keep. Discover must not depend on that button existing.
    await render([F('Clinical/live.docx')])
    expect(byText('Accept all')).toBeUndefined()
    expect(container.textContent).not.toContain('to continue')
    expect(assessBtn().disabled).toBe(false)
  })
})
