/**
 * The review step, rendered: what discovery promises, and which rules will run while it does.
 *
 * Both facts were true of the system and absent from the screen. That asymmetry is the point —
 * neither is discoverable after the fact:
 *
 *   · METADATA ONLY. `_defer_analysis_to_assess()` defaults on (ADR 0020), so a Discover run lists
 *     from metadata and opens nothing. A future change that starts downloading during Discover
 *     would break the strongest claim this product makes about a customer's drive, and would break
 *     it silently, because no screen asserted it. The DOM case below is the assertion.
 *   · WHICH RULES RAN. `_evaluate_discover_lifecycle_rules` tags matched files during the run and
 *     Assess excludes those by default. An inventory looks identical whether two rules ran or
 *     none, so a tag found later is attributable only if the count was on screen at commit time.
 *
 * The load-failure case is the one that would ship quietly: "None enabled" printed because a read
 * failed states that no file will be tagged, on no evidence.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const listDispositionPolicies = vi.fn(async () => [])

vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: {} })),
  setScanLocations: vi.fn(async () => ({ ok: true })),
  listFolders: vi.fn(async () => ({ folders: [{ id: 'hr', name: 'HR' }] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
  listDispositionPolicies: (...a) => listDispositionPolicies(...a),
}))

const { default: ScanScopeWizard } = await import('./ScanScopeWizard.jsx')

async function mount() {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanScopeWizard, {
      showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
      onStartScan: () => {}, scans: [],
    }))
  })
  return container
}

// The review contract is a <dl>; read a row by its term so a match cannot come from prose
// elsewhere on the screen.
function row(c, label) {
  const dt = [...c.querySelectorAll('dt')].find((d) => new RegExp(label, 'i').test(d.textContent))
  return dt?.nextElementSibling?.textContent || ''
}

describe('the promise, before the run', () => {
  it('states that no file is opened', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/no file is opened/i)
    expect(c.textContent).toMatch(/does not download content/i)
  })

  it('says the word discover, not scan, above a button that says discovery', async () => {
    // Two names for one action on one screen: the button has said "Start discovery" since #532
    // while the heading above it still said "Ready to scan" — and "scan" is the word this product
    // uses for the expensive, content-reading thing that happens later.
    const c = await mount()
    expect(c.textContent).toMatch(/Ready to discover/)
    expect(c.textContent, 'the review heading still calls this a scan').not.toMatch(/Ready to scan/)
  })
})

describe('the rules that will run', () => {
  it('reports none when the workspace has no lifecycle rule', async () => {
    listDispositionPolicies.mockResolvedValueOnce([])
    const c = await mount()
    expect(row(c, 'Lifecycle rules')).toMatch(/none enabled/i)
    expect(row(c, 'Lifecycle rules')).toMatch(/No file will be tagged/i)
  })

  it('counts the enabled ones and says what they do', async () => {
    listDispositionPolicies.mockResolvedValueOnce([
      { policy_id: 'p1', name: 'Stale HR', action: 'archive', enabled: 1 },
      { policy_id: 'p2', name: 'Old exports', action: 'delete', enabled: 1 },
      { policy_id: 'p3', name: 'Draft', action: 'archive', enabled: 0 },
    ])
    const c = await mount()
    const r = row(c, 'Lifecycle rules')
    expect(r).toMatch(/2 enabled/)
    expect(r).toMatch(/tagged for review/i)
    // A claim about files, not a banned word — the row's own copy names the actions in order to
    // deny them ("Nothing is moved, trashed or changed"). See discoveryPromise.test.js.
    expect(r, 'the review step says files were archived or deleted')
      .not.toMatch(/\bfiles?\s+(is|are|was|were|will be|have been|has been)\s+\w*\s*(archived|deleted|trashed|removed|moved)\b/i)
  })

  it('shows NO row when the rules could not be read', async () => {
    // The failure that must not become a sentence. "None enabled" here would be a claim that no
    // file gets tagged, made on the strength of a request that never returned.
    listDispositionPolicies.mockRejectedValueOnce(new Error('403'))
    const c = await mount()
    expect(c.textContent, 'a failed rule read rendered as "no rules"').not.toMatch(/Lifecycle rules/)
    expect(c.textContent, 'a failed rule read rendered as "none enabled"').not.toMatch(/none enabled/i)
  })

  it('still lets the run start when the rules are unknown', async () => {
    // The row is evidence, not a gate. A rules endpoint that is down (it is admin-only, and a
    // non-admin gets a 403 every time) must not block discovery.
    listDispositionPolicies.mockRejectedValueOnce(new Error('403'))
    const c = await mount()
    const start = [...c.querySelectorAll('button')].find((b) => /Start discovery/.test(b.textContent))
    expect(start).toBeTruthy()
    expect(start.disabled, 'discovery is blocked when the lifecycle rules cannot be read').toBe(false)
  })
})
