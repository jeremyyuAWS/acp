/**
 * The "Manage <source>" drawer — a source OPERATIONS panel, DOM-level, mounting the real
 * component.
 *
 * What it guards:
 *   - the header states the connection and the last run, and never renders `undefined`
 *     (the shipped subtitle was `undefined · 0 docs · agent: undefined` beside a Healthy card);
 *   - four tabs — Overview / Scope / Rules / Activity — not one long page;
 *   - the compliance material that used to fill this drawer (a scored donut, top flagged
 *     documents, the "agent" paragraph) is GONE. Those are Assess facts and belong there;
 *   - "Needs attention" appears only when something is actionable, and a clean source gets a
 *     status line rather than "All clear in this sample";
 *   - the discovery outcome table is a partition whose rows sum to the total on screen.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED
 * checkout whatever worktree you are in (CLAUDE.md), so a browser check of a worktree change
 * exercises code that does not contain it.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

afterEach(unmountAll)

// The Rules tab reads real disposition policies; FileDrawer (imported for `retentionOf`) pulls
// the same module, so the whole surface is mocked here.
vi.mock('./api.js', () => ({
  listDispositionPolicies: vi.fn(async () => ([
    { policy_id: 'p1', name: 'Archive files not modified for 7 years', action: 'archive', enabled: true,
      match: [{ field: 'age_days', op: 'gt', value: 2555 }] },
    { policy_id: 'p2', name: 'Temporary files older than 90 days', action: 'delete', enabled: true,
      match: [{ field: 'age_days', op: 'gt', value: 90 }] },
  ])),
  getInventoryDiff: vi.fn(async () => ({ no_baseline: true, summary: {} })),
  previewDispositionPolicy: vi.fn(async (id) => ({
    policy_id: id, would_match: 5,
    documents: [
      { doc_id: 'sp1', source: 'sharepoint', path: '/Finance/a.docx', department: 'Finance' },
      { doc_id: 'sp2', source: 'sharepoint', path: '/Finance/b.docx', department: 'Finance' },
      { doc_id: 'gd1', source: 'drive', path: '/HR/c.docx', department: 'HR' },
      { doc_id: 'gd2', source: 'drive', path: '/HR/d.docx', department: 'HR' },
      { doc_id: 'gd3', source: 'drive', path: '/HR/e.docx', department: 'HR' },
    ],
  })),
  listDispositionApprovals: vi.fn(async () => ([
    { id: 'a1', doc_id: 'sp:1', policy_id: 'p2', action: 'delete', result: 'pending_approval',
      detail: 'matched temporary-files rule', ts: '2026-08-18T11:00:00Z',
      source: 'sharepoint', path: '/Finance/tmp.docx', document_exists: true },
    { id: 'a2', doc_id: 'gd:9', policy_id: 'p1', action: 'archive', result: 'pending_approval',
      detail: 'matched archive rule', ts: '2026-08-18T11:00:00Z',
      source: 'drive', path: '/HR/old.docx', document_exists: true },
  ])),
  approveDisposition: vi.fn(async () => ({ result: 'approved' })),
  listDispositionAudit: vi.fn(async () => ([
    { id: 'h1', doc_id: 'sp:1', policy_id: 'p1', action: 'archive', result: 'approved',
      detail: 'approved by admin — decision recorded, file not touched',
      ts: '2026-08-18T12:00:00Z', source: 'sharepoint', path: '/Finance/old.docx',
      document_exists: true, policy_name: 'Archive files not modified for 7 years' },
    { id: 'h2', doc_id: 'sp:2', policy_id: 'gone', action: 'delete', result: 'rejected',
      detail: 'declined by admin', ts: '2026-08-17T12:00:00Z', source: 'sharepoint',
      path: '/Finance/tmp.docx', document_exists: true, policy_name: null },
    { id: 'h3', doc_id: 'gd:5', policy_id: 'p1', action: 'archive', result: 'applied',
      detail: 'moved', ts: '2026-08-16T12:00:00Z', source: 'drive', path: '/HR/x.docx',
      document_exists: true, policy_name: 'Archive files not modified for 7 years' },
  ])),
  rejectDisposition: vi.fn(async () => ({ result: 'rejected' })),
  getScanTraces: vi.fn(async () => []),
  getScanRemediationDiffs: vi.fn(async () => []),
  remediateFile: vi.fn(async () => ({})),
  getJob: vi.fn(async () => ({})),
  getFileEvidence: vi.fn(async () => ([])),
  getScanProposals: vi.fn(async () => ([])),
}))

const { default: SourceDrawer, policyMatchRows } = await import('./SourceDrawer.jsx')

const ONEDRIVE = { id: 'sp-root', type: 'onedrive', name: 'OneDrive', user: 'acp@utsw.edu',
  access: 'read-only', agent: 'continuous' }

// Rows keyed `sharepoint` — the OneDrive card's id is `sp-root`, and the mismatch is the bug.
const FILE = (over = {}) => ({ file: 'policy.docx', type: 'docx', source: 'sharepoint',
  owner: 'Rae Lin', department: 'HR', sizeKB: 200, tags: [], issues: [], ageDays: 30, views90d: 400, ...over })

const RUN = (over = {}) => ({ id: 'run-1', source: 'sharepoint', started_at: '2026-08-18T11:41:18Z',
  completed_at: '2026-08-18T11:50:00Z', files: 4, error: 0, ...over })

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(SourceDrawer, {
      source: ONEDRIVE, files: [FILE()], scans: [RUN()], onClose: vi.fn(), ...props,
    }))
  })
  await act(async () => { await Promise.resolve() })
  return container
}
const click = async (el) => { await act(async () => { el.click() }); await act(async () => { await Promise.resolve() }) }
const tab = (c, name) => [...c.querySelectorAll('[role="tab"]')].find((b) => b.textContent.trim() === name)

describe('the source operations drawer', () => {
  it('decodes production JSON match fields instead of crashing the Rules tab', () => {
    expect(policyMatchRows('[{"field":"age_days","op":"gt","value":2555}]')).toEqual([
      { field: 'age_days', op: 'gt', value: 2555 },
    ])
    expect(policyMatchRows('{"field":"type","op":"eq","value":"pdf"}')).toEqual([
      { field: 'type', op: 'eq', value: 'pdf' },
    ])
    expect(policyMatchRows('not-json')).toEqual([])
  })

  it('is titled "Manage <source>" and states the connection and the last run', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/Manage OneDrive/)
    expect(c.textContent).toMatch(/Connected/)
    expect(c.textContent).toMatch(/Last discovery/)
  })

  it('never renders the string "undefined"', async () => {
    // The shipped subtitle was `${source.dept} · ${files} docs · agent: ${source.agent}` over a
    // card row that has none of those fields — it printed them anyway.
    const bare = { id: 'sp-root', type: 'onedrive', name: 'OneDrive' }
    const c = await mount({ source: bare, files: [], scans: [] })
    expect(c.textContent).not.toMatch(/undefined/)
    expect(c.textContent).toMatch(/No discovery completed/)
  })

  it('finds the source’s files even though the card id is not the file rows’ source key', async () => {
    const c = await mount({ files: [FILE(), FILE({ file: 'b.pdf', type: 'pdf' }), FILE({ file: 'other.docx', source: 'gdrive' })] })
    // Two OneDrive rows, not zero (the shipped filter's answer) and not three (everyone's rows).
    expect([...c.querySelectorAll('td')].at(-1).textContent).toBe('2')
    expect(c.textContent).not.toMatch(/0 docs/)
  })

  it('offers exactly the four operational tabs', async () => {
    const c = await mount()
    expect([...c.querySelectorAll('[role="tab"]')].map((b) => b.textContent.trim()))
      .toEqual(['Overview', 'Scope', 'Rules', 'Activity'])
  })

  it('drops the compliance dashboard — no donut, no flagged list, no agent paragraph', async () => {
    const c = await mount({ files: [FILE({ status: 'issues', score: 41, issues: [{ wcag: 'SC_1_1_1' }] })] })
    expect(c.textContent).not.toMatch(/Compliance · sampled documents/)
    expect(c.textContent).not.toMatch(/Top flagged documents/)
    expect(c.textContent).not.toMatch(/auto-discovers, tags, and re-scans/)
    expect(c.textContent).not.toMatch(/All clear in this sample/)
    expect(c.querySelector('svg circle')).toBeNull()
  })

  it('shows a discovery outcome partition whose rows sum to the total', async () => {
    const c = await mount({ files: [
      FILE(),                                            // assessable
      FILE({ file: 'clip.mp4', type: 'video' }),         // unsupported
      FILE({ file: 'old.docx', ageDays: 900, views90d: 3 }), // archive candidate
      FILE({ file: 'locked.pdf', type: 'pdf', locked: true, openIssue: 'Access denied' }),
    ] })
    expect(c.textContent).toMatch(/Available for assessment/)
    expect(c.textContent).toMatch(/Unsupported, inventoried only/)
    expect(c.textContent).toMatch(/Tagged for archive/)
    expect(c.textContent).toMatch(/Tagged for deletion review/)
    expect(c.textContent).toMatch(/Total discovered/)
    const total = [...c.querySelectorAll('td')].at(-1).textContent
    expect(total).toBe('4')
  })

  it('reports a run that could not read files as completed WITH WARNINGS, and raises it', async () => {
    const c = await mount({ scans: [RUN({ error: 18 })] })
    expect(c.textContent).toMatch(/Completed with warnings/)
    expect(c.textContent).toMatch(/Needs attention/)
    expect(c.textContent).toMatch(/18 files could not be read/)
  })

  it('says nothing at all when nothing needs attention', async () => {
    const c = await mount()
    expect(c.textContent).toMatch(/No discovery issues/)
    expect(c.textContent).not.toMatch(/Needs attention/)
  })

  it('Scope names the authorised boundary and keeps un-set fields visible', async () => {
    const c = await mount()
    await click(tab(c, 'Scope'))
    expect(c.textContent).toMatch(/Discovery scope/)
    expect(c.textContent).toMatch(/acp@utsw\.edu/)
    expect(c.textContent).toMatch(/Read files · read metadata/)
    expect(c.textContent).toMatch(/Write-back/)
    expect(c.textContent).toMatch(/Not enabled/)
    // Root is not configured on this card — the field stays, with a stated absence.
    expect(c.textContent).toMatch(/Not configured/)
  })

  it('Scope keeps rule exclusions, permission denials and read failures apart', async () => {
    const c = await mount({
      files: [FILE({ file: 'x.docx', excluded: true }), FILE({ file: 'y.pdf', type: 'pdf', locked: true })],
      scans: [RUN({ error: 3 })],
    })
    await click(tab(c, 'Scope'))
    expect(c.textContent).toMatch(/Excluded by a configured rule/)
    expect(c.textContent).toMatch(/Inaccessible — permission denied/)
    expect(c.textContent).toMatch(/Failed during the last discovery run/)
  })

  it('Rules lists the real discovery policies and never calls a delete rule a delete', async () => {
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/Archive files not modified for 7 years/)
    expect(c.textContent).toMatch(/deletion review/)
    expect(c.textContent).toMatch(/ACP never deletes on a rule alone/)
  })

  it('Activity is a run log with the facts needed to troubleshoot one', async () => {
    const c = await mount({ scans: [RUN(), RUN({ id: 'run-0', completed_at: '2026-08-17T11:48:00Z', error: 18 })] })
    await click(tab(c, 'Activity'))
    expect(c.querySelectorAll('details').length).toBe(2)
    expect(c.textContent).toMatch(/Run ID/)
    expect(c.textContent).toMatch(/Duration/)
    expect(c.textContent).toMatch(/18 could not be read/)
  })

  it('keeps discovery reachable from a persistent footer', async () => {
    const onScan = vi.fn()
    const c = await mount({ onScan })
    await click(tab(c, 'Activity'))
    const run = [...c.querySelectorAll('button')].find((b) => /Run discovery/.test(b.textContent))
    expect(run).toBeTruthy()
    await click(run)
    expect(onScan).toHaveBeenCalledWith(ONEDRIVE)
  })

  it('hands off to Assess with a count rather than a compliance summary', async () => {
    const onOpenAssess = vi.fn()
    const c = await mount({ onOpenAssess, files: [FILE(), FILE({ file: 'clip.mp4', type: 'video' })] })
    expect(c.textContent).toMatch(/1 discovered file is eligible for assessment/)
    await click([...c.querySelectorAll('button')].find((b) => /Open Assess/.test(b.textContent)))
    expect(onOpenAssess).toHaveBeenCalled()
  })
})

describe('the Rules tab match counts and review queues', () => {
  const link = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))

  it('does not run the preview scans until the Rules tab is opened', async () => {
    // Each preview evaluates the policy over the WHOLE documents table in Python. Firing them on
    // drawer open would make looking at Overview cost N full-table scans.
    const api = await import('./api.js')
    api.previewDispositionPolicy.mockClear()
    const c = await mount()
    expect(api.previewDispositionPolicy).not.toHaveBeenCalled()
    await click(tab(c, 'Rules'))
    expect(api.previewDispositionPolicy).toHaveBeenCalled()
  })

  it('splits the match count by boundary instead of reporting the estate total as the source’s', async () => {
    // The preview matched 5 documents across all sources; 2 of them are this source's.
    // "5 matched" under a per-source heading would be a true number saying a false thing.
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/2 matched in OneDrive/)
    expect(c.textContent).toMatch(/5 across all sources/)
  })

  it('lists this source’s matches only, on demand', async () => {
    const c = await mount()
    await click(tab(c, 'Rules'))
    await click(link(c, /View matches/))
    expect(c.textContent).toMatch(/\/Finance\/a\.docx/)
    expect(c.textContent).not.toMatch(/\/HR\/c\.docx/)     // another source's match
  })

  it('surfaces archive and deletion review queues with what they mean', async () => {
    const c = await mount({ files: [
      FILE(),
      FILE({ file: 'old.docx', ageDays: 900, views90d: 3 }),      // archive candidate
    ] })
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/1 Archive candidates/)
    expect(c.textContent).toMatch(/Reversible/)
  })

  it('the queue counts agree with the Overview partition by construction', async () => {
    const files = [FILE(), FILE({ file: 'o1.docx', ageDays: 900, views90d: 3 }),
                   FILE({ file: 'o2.docx', ageDays: 950, views90d: 2 })]
    const c = await mount({ files })
    // Overview's partition row…
    const overviewArchive = [...c.querySelectorAll('tr')]
      .find((r) => /Tagged for archive/.test(r.textContent))
      .querySelectorAll('td')[1].textContent
    await click(tab(c, 'Rules'))
    expect(overviewArchive).toBe('2')
    expect(c.textContent).toMatch(/2 Archive candidates/)
  })

  it('says nothing is awaiting review rather than showing empty queues', async () => {
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/Nothing is awaiting review/)
  })

  it('a failed preview loses the count, not the rule', async () => {
    const api = await import('./api.js')
    api.previewDispositionPolicy.mockRejectedValueOnce(new Error('boom'))
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/Could not count matches/)
    expect(c.textContent).toMatch(/Archive files not modified for 7 years/)
  })
})

describe('the pending-approval queue', () => {
  const link = (c, re) => [...c.querySelectorAll('button')].find((b) => re.test(b.textContent))

  it('shows only this source’s approvals, and says how many are elsewhere', async () => {
    // disposition_audit has no source column — the route joins it in from `documents`. Rendering
    // the whole estate's queue under a heading naming one source is the boundary error the rule
    // match counts already avoid.
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/\/Finance\/tmp\.docx/)
    expect(c.textContent).not.toMatch(/\/HR\/old\.docx/)
    expect(c.textContent).toMatch(/1 more pending on other sources/)
  })

  it('states that Approve records a decision and does not touch the file', async () => {
    // ACP holds read-only scopes and the executor is Drive-only, so a button implying a move
    // would promise what the deployment cannot do.
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/Approve records the decision and leaves the file untouched/)
    expect(c.textContent).toMatch(/read-only access/)
  })

  it('approves with execute:false — never executing from this panel', async () => {
    const api = await import('./api.js')
    api.approveDisposition.mockClear()
    const c = await mount()
    await click(tab(c, 'Rules'))
    await click(link(c, /Approve/))
    expect(api.approveDisposition).toHaveBeenCalledWith('a1', { execute: false })
  })

  it('rejects through the reject endpoint', async () => {
    const api = await import('./api.js')
    api.rejectDisposition.mockClear()
    const c = await mount()
    await click(tab(c, 'Rules'))
    await click(link(c, /Reject/))
    expect(api.rejectDisposition).toHaveBeenCalledWith('a1')
  })

  it('shows a vanished document to every source rather than hiding it', async () => {
    // It belongs to no source, and it is the row most in need of a decision.
    const api = await import('./api.js')
    api.listDispositionApprovals.mockResolvedValueOnce([
      { id: 'a3', doc_id: 'ghost:1', action: 'delete', result: 'pending_approval',
        detail: 'queued', source: null, path: null, document_exists: false },
    ])
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/document no longer exists/)
  })

  it('says nothing is awaiting approval rather than showing an empty box', async () => {
    const api = await import('./api.js')
    api.listDispositionApprovals.mockResolvedValueOnce([])
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/Nothing is awaiting approval for this source/)
  })

  it('a failed queue load does not imply anything ran', async () => {
    const api = await import('./api.js')
    api.listDispositionApprovals.mockRejectedValueOnce(new Error('boom'))
    const c = await mount()
    await click(tab(c, 'Rules'))
    expect(c.textContent).toMatch(/Could not load the approval queue/)
    expect(c.textContent).toMatch(/none of them run without a decision/)
  })
})

describe('the lifecycle audit trail', () => {
  it('makes the source-scoped run history explicit and discoverable', async () => {
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/Run history/)
    expect(c.textContent).toMatch(/this source only, newest first/)
    expect(c.textContent).toMatch(/Expand a run for its timing, coverage, errors, owner, and run ID/)
  })

  it('lives on Activity, beside what the source has been doing', async () => {
    const c = await mount()
    expect(c.textContent).not.toMatch(/Lifecycle decisions/)   // not on Overview
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/Lifecycle decisions/)
  })

  it('names the rule rather than its id', async () => {
    // "archive sp:1 under p1" is four ids and an enum — an auditor reading that back cannot
    // tell what happened.
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/Archive files not modified for 7 years/)
    expect(c.textContent).not.toMatch(/under p1/)
  })

  it('says a deleted rule is gone instead of printing its id as a name', async () => {
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/no longer configured/)
  })

  it('scopes to this source and states how many are elsewhere', async () => {
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/\/Finance\/old\.docx/)
    expect(c.textContent).not.toMatch(/\/HR\/x\.docx/)      // a Drive row
    expect(c.textContent).toMatch(/1 more recorded on other sources/)
  })

  it('says what each outcome MEANT for the file, not just its stored value', async () => {
    // 'approved' alone does not tell a reader whether anything moved.
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/decision recorded · file not touched/)
    expect(c.textContent).toMatch(/declined · file not touched/)
  })

  it('keeps rejected decisions in the record', async () => {
    // They leave the queue; they must not leave the trail, or the append-only table has no point.
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/rejected/)
  })

  it('says nothing was recorded rather than showing an empty list', async () => {
    const api = await import('./api.js')
    api.listDispositionAudit.mockResolvedValueOnce([])
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/No lifecycle decisions recorded for this source/)
  })

  it('a failed load does not imply the record is damaged', async () => {
    const api = await import('./api.js')
    api.listDispositionAudit.mockRejectedValueOnce(new Error('boom'))
    const c = await mount()
    await click(tab(c, 'Activity'))
    expect(c.textContent).toMatch(/Could not load the lifecycle trail/)
    expect(c.textContent).toMatch(/append-only/)
  })
})
