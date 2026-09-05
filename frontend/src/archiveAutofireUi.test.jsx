import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

// The two archive auto-fire screens, asserted at the DOM level.
//
// AT THE DOM AND NOT IN A BROWSER, deliberately: CLAUDE.md records that the preview server runs
// vite with the SHARED CHECKOUT as its root whatever worktree you are in, so a browser check of
// a change made in a worktree exercises code that does not contain it — and passes. A screenshot
// from that server is evidence about main, not about this branch.

const policy = {
  configured: true,
  policy: {
    enabled: true, kill_switch: false, dry_run: true, source_connections: ['sharepoint:d1'],
    rule_ids: ['r1'], required_evidence: ['metadata_link'], confirmed_families: [],
    min_replacement_age_days: 30, archive_root: 'Archive', preserve_hierarchy: true,
    max_actions_per_run: 25, max_actions_per_day: 100,
  },
  snapshot_id: 'snap1', updated_at: '2026-09-05T00:00:00Z', updated_by: 'admin@example.com',
  evidence_types: [
    { type: 'metadata_link', label: 'Replacement metadata names this document (retentionOf / supersedes)' },
    { type: 'admin_mapping', label: 'An administrator confirmed this document-family mapping' },
  ],
  auto_sources: ['sharepoint', 'onedrive'],
  problem: '',
  notice: 'Age, filename similarity and inactivity never authorize an automatic move.',
}

const candidates = {
  scan_id: 's1', snapshot_id: 'snap1', dry_run: true,
  counts: { eligible: 1, completed: 1, blocked: 1 },
  items: [
    { file: 'Clinical-Access-v2.docx', path: 'Policies/2024/Clinical-Access-v2.docx',
      source_connection: 'sharepoint:d1', state: 'eligible_auto',
      reason: 'A newer item is proven to supersede this document.',
      destination_path: 'Archive/Policies/2024/Clinical-Access-v2.docx',
      evidence_summary: 'Replacement metadata names this document.',
      evidence: [{ type: 'metadata_link', source_item_id: 'item-old', replacement_item_id: 'item-new',
                   replacement_path: 'Policies/2025/Clinical-Access-v3.docx',
                   detail: 'Clinical-Access-v3.docx carries a supersedes value naming this document.' }],
      rejected_evidence: [] },
    { file: 'Old-Handbook.docx', path: 'HR/2019/Old-Handbook.docx',
      source_connection: 'sharepoint:d1', state: 'recommend_only',
      reason: 'No supersession evidence links this document to a newer replacement.',
      destination_path: '', evidence_summary: 'No supersession evidence.', evidence: [],
      rejected_evidence: [] },
    { file: 'Half-Moved.docx', path: 'HR/2019/Half-Moved.docx',
      source_connection: 'sharepoint:d1', state: 'recovery_required',
      reason: "The source system's response to the move was ambiguous.",
      destination_path: 'Archive/HR/2019/Half-Moved.docx', evidence_summary: '', evidence: [],
      rejected_evidence: [] },
  ],
}

const api = vi.hoisted(() => ({
  getArchivePolicy: vi.fn(),
  updateArchivePolicy: vi.fn(),
  setArchiveKillSwitch: vi.fn(),
  getArchiveCandidates: vi.fn(),
  runArchiveAutofire: vi.fn(),
}))
vi.mock('./api.js', () => api)

let matchMediaReduced = false
vi.mock('./a11y.js', () => ({ prefersReducedMotion: () => matchMediaReduced }))

import ArchiveAutofireOption from './ArchiveAutofireOption.jsx'
import ArchiveAutofirePanel from './ArchiveAutofirePanel.jsx'

let host
const mount = async (element) => {
  await act(async () => { createRoot(host).render(element); await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.appendChild(host)
  matchMediaReduced = false
  api.getArchivePolicy.mockResolvedValue(JSON.parse(JSON.stringify(policy)))
  api.updateArchivePolicy.mockResolvedValue(JSON.parse(JSON.stringify(policy)))
  api.setArchiveKillSwitch.mockResolvedValue(JSON.parse(JSON.stringify(policy)))
  api.getArchiveCandidates.mockResolvedValue(JSON.parse(JSON.stringify(candidates)))
  api.runArchiveAutofire.mockResolvedValue({ completed: 1 })
})
afterEach(() => { host.remove(); vi.clearAllMocks() })

// ── The rule editor option ───────────────────────────────────────────────────

describe('the lifecycle rule editor option', () => {
  it('warns that age never triggers a move, next to the control and not in a footnote', async () => {
    await mount(<ArchiveAutofireOption rules={[{ policy_id: 'r1', name: 'Superseded policies' }]} />)
    const text = host.textContent
    expect(text).toMatch(/Age never triggers a move/)
    // Before the toggle in document order — a correction a reader meets after deciding is not a
    // correction.
    expect(text.indexOf('Age never triggers a move'))
      .toBeLessThan(text.indexOf('Archive proven superseded files without asking me'))
  })

  it('keeps the warning visible when the option is switched OFF', async () => {
    api.getArchivePolicy.mockResolvedValue({ ...policy, policy: { ...policy.policy, enabled: false } })
    await mount(<ArchiveAutofireOption rules={[]} />)
    // The wrong assumption is formed by the toggle EXISTING, so the correction cannot be
    // conditional on its state.
    expect(host.textContent).toMatch(/Age never triggers a move/)
  })

  it('shows the evidence, destination, ceiling and dry-run status once it is on', async () => {
    await mount(<ArchiveAutofireOption rules={[{ policy_id: 'r1', name: 'Superseded policies' }]} />)
    const text = host.textContent
    expect(text).toMatch(/retentionOf/)
    expect(text).toMatch(/Archive/)
    expect(text).toMatch(/100 files a day/)
    expect(text).toMatch(/Dry run/)
  })

  it('offers the kill switch and says what it does to work in flight', async () => {
    api.getArchivePolicy.mockResolvedValue(
      { ...policy, policy: { ...policy.policy, kill_switch: true } })
    await mount(<ArchiveAutofireOption rules={[]} />)
    expect(host.textContent).toMatch(/Kill switch on/)
    expect(host.textContent).toMatch(/already in flight is finished or explicitly failed/)
  })

  it('says the settings are unavailable rather than implying the feature is off', async () => {
    api.getArchivePolicy.mockRejectedValue(new Error('boom'))
    await mount(<ArchiveAutofireOption rules={[]} />)
    expect(host.textContent).toMatch(/could not be loaded/)
    expect(host.textContent).not.toMatch(/Archive proven superseded files without asking me/)
  })

  it('surfaces a refused save inline instead of failing silently', async () => {
    api.updateArchivePolicy.mockRejectedValue(new Error('403 Forbidden'))
    await mount(<ArchiveAutofireOption rules={[]} />)
    const checkbox = [...host.querySelectorAll('input[type=checkbox]')][0]
    await act(async () => { checkbox.click(); await Promise.resolve() })
    await act(async () => { await Promise.resolve() })
    expect(host.querySelector('[role=alert]').textContent).toMatch(/platform admin/)
  })

  it('every control is reachable by keyboard — no click-only affordance', async () => {
    await mount(<ArchiveAutofireOption rules={[{ policy_id: 'r1', name: 'r' }]} />)
    const focusable = host.querySelectorAll('input, button, select, textarea')
    expect(focusable.length).toBeGreaterThan(5)
    for (const el of focusable) expect(el.tabIndex).toBeGreaterThanOrEqual(0)
    // Nothing is a div pretending to be a control.
    expect(host.querySelectorAll('[onclick]').length).toBe(0)
  })
})

// ── The discovery lane ───────────────────────────────────────────────────────

describe('the discovery archive lane', () => {
  it('names each state in words, never by color alone', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    const text = host.textContent
    expect(text).toMatch(/Eligible for automatic archive/)
    expect(text).toMatch(/Recommended for archive/)
    expect(text).toMatch(/Recovery required/)
  })

  it('never renders an unconfirmed move as archived', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    const row = [...host.querySelectorAll('li')]
      .find((li) => li.textContent.includes('Half-Moved.docx'))
    expect(row.textContent).toMatch(/Recovery required/)
    expect(row.textContent).not.toMatch(/Automatically archived/)
  })

  it('states measured counts with no percentage', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    expect(host.textContent).toMatch(/1 eligible · 1 completed · 1 blocked · 0 remaining/)
    expect(host.textContent).not.toMatch(/%/)
  })

  it('says a dry run moves nothing', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    expect(host.textContent).toMatch(/no file is moved/)
  })

  // Rows are ordered by urgency (recovery-required first), so a test must reach for the row it
  // means rather than the first disclosure on the page — which is a different document.
  const discloseIn = (file) => [...host.querySelectorAll('li')]
    .find((li) => li.textContent.includes(file))
    .querySelector('button')

  it('orders the list by urgency, not alphabetically', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    const files = [...host.querySelectorAll('li')].map((li) => li.textContent)
    expect(files[0]).toMatch(/Recovery required/)
  })

  it('lets a person inspect the evidence before anything runs', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    const toggle = discloseIn('Clinical-Access-v2.docx')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    await act(async () => { toggle.click(); await Promise.resolve() })
    expect(host.textContent).toMatch(/carries a supersedes value naming this document/)
    expect(host.textContent).toMatch(/item-old/)
    expect(host.textContent).toMatch(/item-new/)
  })

  it('returns focus to the row that opened the evidence when it closes', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    const toggle = discloseIn('Clinical-Access-v2.docx')
    await act(async () => { toggle.click(); await Promise.resolve() })
    await act(async () => { discloseIn('Clinical-Access-v2.docx').click(); await Promise.resolve() })
    // Not the top of the document: on a list of forty candidates, being dropped there after every
    // inspection means re-traversing the list forty times.
    expect(document.activeElement).not.toBe(document.body)
    expect(document.activeElement.textContent).toBe('Show the evidence')
  })

  it('announces through a POLITE live region, not an assertive one', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    const region = host.querySelector('[aria-live]')
    expect(region.getAttribute('aria-live')).toBe('polite')
  })

  it('does not auto-refresh under reduced motion, and offers an explicit refresh instead', async () => {
    matchMediaReduced = true
    vi.useFakeTimers()
    try {
      await mount(<ArchiveAutofirePanel scanId="s1" />)
      const before = api.getArchiveCandidates.mock.calls.length
      await act(async () => { vi.advanceTimersByTime(60000) })
      expect(api.getArchiveCandidates.mock.calls.length).toBe(before)
      expect([...host.querySelectorAll('button')].some((b) => b.textContent === 'Refresh')).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('offers no run button when nothing is eligible, and says so', async () => {
    api.getArchiveCandidates.mockResolvedValue({ ...candidates, counts: { eligible: 0 } })
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    const run = [...host.querySelectorAll('button')].find((b) => /^Archive /.test(b.textContent))
    expect(run.disabled).toBe(true)
    expect(host.textContent).toMatch(/Nothing in this scan is eligible/)
  })

  it('reports a failed load without claiming the lane is empty', async () => {
    api.getArchiveCandidates.mockRejectedValue(new Error('boom'))
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    expect(host.querySelector('[role=alert]').textContent).toMatch(/could not be loaded/)
    expect(host.textContent).not.toMatch(/No archive candidates were recorded/)
  })

  it('restates that age never authorizes a move, on the results surface too', async () => {
    await mount(<ArchiveAutofirePanel scanId="s1" />)
    expect(host.textContent).toMatch(/Age never authorizes an automatic move/)
  })
})
