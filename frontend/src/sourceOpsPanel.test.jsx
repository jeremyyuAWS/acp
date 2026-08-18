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
  getScanTraces: vi.fn(async () => []),
  getScanRemediationDiffs: vi.fn(async () => []),
  remediateFile: vi.fn(async () => ({})),
  getJob: vi.fn(async () => ({})),
  getFileEvidence: vi.fn(async () => ([])),
  getScanProposals: vi.fn(async () => ([])),
}))

const { default: SourceDrawer } = await import('./SourceDrawer.jsx')

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
