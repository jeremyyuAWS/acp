import { describe, it, expect } from 'vitest'
import {
  laneOf, LANES, effortSecOf, effortLabel, isResolved, issueLabel, locationLabel, rowModel,
  tabOf, tabCounts, matchesTab, sortQueue, groupByDocument, nextUnresolvedId, progress,
  normSc, autoFixRows, railColorOf, NEUTRAL_RAIL, workflowStatusOf,
} from './remediationInboxModel.js'

const F = {
  autoFixed: { id: 1, file: 'Security-Brief-14.docx', title: 'DOCX · Heading contrast is too low', page: 1, severity: 'SERIOUS', autoApplied: true },
  suggested: { id: 2, file: 'Security-Brief-14.docx', title: 'DOCX · Image needs alt text', page: 3, severity: 'CRITICAL', aiDraftable: true, hasProposal: true, after: 'A bar chart' },
  manual: { id: 3, file: 'Policy.pdf', title: 'PDF · Scanned page, no text', severity: 'SERIOUS' },
  blocked: { id: 4, file: 'Policy.pdf', title: 'PDF · Corrupt object', severity: 'MINOR', status: 'blocked' },
  recheck: { id: 5, file: 'Report.xlsx', title: 'XLSX · edited, needs recheck', status: 'recheck' },
}
const ALL = Object.values(F)

describe('lane taxonomy', () => {
  it('maps a finding to exactly one lane by status then remediation shape', () => {
    expect(laneOf(F.autoFixed)).toBe(LANES.review)   // green
    expect(laneOf(F.suggested)).toBe(LANES.apply)    // blue
    expect(laneOf(F.manual)).toBe(LANES.manual)      // amber
    expect(laneOf(F.blocked)).toBe(LANES.blocked)    // red
    expect(laneOf(F.recheck)).toBe(LANES.recheck)    // gray
  })
  it('status wins over shape: a blocked finding with a proposal is still blocked', () => {
    expect(laneOf({ hasProposal: true, after: 'x', status: 'blocked' })).toBe(LANES.blocked)
  })
  it('each lane has a distinct rail colour', () => {
    const rails = Object.values(LANES).map((l) => l.rail)
    expect(new Set(rails).size).toBe(rails.length)
  })
  it('a not-applicable (out-of-scope) decision resolves the finding and lands it in Completed', () => {
    const f = { id: 7, hasProposal: true, after: 'x' }
    const decisions = { 7: { state: 'not_applicable' } }
    expect(isResolved(f, decisions)).toBe(true)
    expect(workflowStatusOf(f, decisions)).toBe('completed')   // settled, no re-scan to await
  })
  it('reserves a coloured rail for attention lanes; everyday lanes get a neutral rail', () => {
    // Blocked + rejected-handoff are the only lanes a reviewer must actively unblock.
    expect(railColorOf(LANES.blocked)).toBe(LANES.blocked.color)
    expect(railColorOf(LANES.handoff)).toBe(LANES.handoff.color)
    // The common lanes no longer paint a saturated vertical bar on every row.
    expect(railColorOf(LANES.manual)).toBe(NEUTRAL_RAIL)
    expect(railColorOf(LANES.review)).toBe(NEUTRAL_RAIL)
    expect(railColorOf(LANES.apply)).toBe(NEUTRAL_RAIL)
    expect(railColorOf(LANES.recheck)).toBe(NEUTRAL_RAIL)
  })
})

describe('effort', () => {
  it('reviewing an auto fix is quick; a manual re-author is the slow one', () => {
    expect(effortSecOf(F.autoFixed)).toBeLessThan(effortSecOf(F.manual))
    expect(effortLabel(F.autoFixed)).toBe('~5 sec')
    expect(effortLabel(F.manual)).toBe('~2 min')
    expect(effortLabel(F.blocked)).toBe('—')
  })
  it('an explicit effortSec overrides the lane default', () => {
    expect(effortSecOf({ ...F.manual, effortSec: 30 })).toBe(30)
  })
})

describe('row model', () => {
  it('the dominant text is the plain issue, filename stripped of its format prefix', () => {
    expect(issueLabel(F.autoFixed)).toBe('Heading contrast is too low')
    expect(locationLabel(F.autoFixed)).toBe('Page 1')
  })
  it('communicates the six facts a queue row needs', () => {
    const r = rowModel(F.autoFixed)
    expect(r.issue).toBe('Heading contrast is too low')
    expect(r.did).toBe('ACP fixed it — review the change')
    expect(r.action).toBe('Approve fix')
    expect(r.lane.rail).toBe('green')
    expect(r.unread).toBe(true)
  })
})

describe('resolution + tabs', () => {
  it('a recorded decision resolves a finding and clears its unread emphasis', () => {
    expect(isResolved(F.suggested, {})).toBe(false)
    expect(isResolved(F.suggested, { 2: { state: 'accepted' } })).toBe(true)
    expect(rowModel(F.suggested, { 2: { state: 'accepted' } }).unread).toBe(false)
  })
  it('tab counts partition the queue exactly', () => {
    const c = tabCounts(ALL)
    expect(c.all).toBe(5)
    expect(c['auto-fixed'] + c.manual + c.blocked + c.resolved).toBe(5)
    expect(c.manual).toBe(1)
    expect(c.blocked).toBe(1)
  })
  it('resolved findings move to the Resolved tab', () => {
    const dec = { 1: { state: 'accepted' } }
    expect(tabOf(F.autoFixed, dec)).toBe('resolved')
    expect(matchesTab(F.autoFixed, 'resolved', dec)).toBe(true)
    expect(matchesTab(F.autoFixed, 'auto-fixed', dec)).toBe(false)
  })
})

describe('sorting + grouping', () => {
  it('priority puts the critical finding first', () => {
    expect(sortQueue(ALL, 'priority').map((f) => f.id)[0]).toBe(2)
  })
  it('fastest orders by ascending effort', () => {
    expect(sortQueue(ALL, 'fastest').map((f) => f.id)).toEqual([4, 1, 5, 2, 3])
  })
  it('group-by-document keeps first-appearance order', () => {
    const g = groupByDocument(ALL)
    expect(g.map((x) => x.file)).toEqual(['Security-Brief-14.docx', 'Policy.pdf', 'Report.xlsx'])
    expect(g[0].items).toHaveLength(2)
  })
})

describe('auto-advance — the behaviour that makes it feel fast', () => {
  it('after acting, selects the next unresolved finding', () => {
    const dec = { 2: { state: 'accepted' } }
    expect(nextUnresolvedId(ALL, 1, dec)).toBe(3) // skips the just-resolved #2
  })
  it('wraps once to the start', () => {
    expect(nextUnresolvedId(ALL, 5, { 2: { state: 'accepted' } })).toBe(1)
  })
  it('returns null at inbox zero', () => {
    const allResolved = Object.fromEntries(ALL.map((f) => [f.id, { state: 'accepted' }]))
    expect(nextUnresolvedId(ALL, 1, allResolved)).toBeNull()
  })
  it('progress reports resolved of total', () => {
    expect(progress(ALL, { 1: { state: 'accepted' }, 4: { state: 'rejected' } })).toEqual({ resolved: 2, total: 5 })
  })
})

describe('auto-applied fixes fold into the green review lane', () => {
  const NAME = { '1.4.3': 'Contrast (Minimum)', '1.1.1': 'Non-text Content' }
  const FIXES = [
    { file: 'Brief.docx', rule_id: 'SC_1_4_3', before: '#D9D9D9', after: '#2F6FED' },
    { file: 'Policy.pdf', sc: '1.1.1', value: 'A bar chart of revenue' },  // applied_fixes shape
  ]

  it('normSc strips SC_/WCAG_ prefixes and underscores', () => {
    expect(normSc('SC_1_4_3')).toBe('1.4.3')
    expect(normSc('WCAG_2.4.6')).toBe('2.4.6')
    expect(normSc('1.1.1')).toBe('1.1.1')
  })

  it('each auto fix becomes a green review-lane row with before/after and a namespaced id', () => {
    const rows = autoFixRows(FIXES, (sc) => NAME[sc] || sc)
    expect(rows).toHaveLength(2)
    expect(laneOf(rows[0])).toBe(LANES.review)                     // green
    expect(rows[0].id).toMatch(/^af:Brief\.docx:1\.4\.3/)          // namespaced, no collision with numeric ids
    expect(rowModel(rows[0]).issue).toBe('Contrast (Minimum)')     // plain criterion name
    expect(rowModel(rows[0]).did).toBe('ACP fixed it — review the change')
    expect(rowModel(rows[0]).action).toBe('Approve fix')
    expect(rows[0].before).toBe('#D9D9D9')
    expect(rows[0].after).toBe('#2F6FED')
    // applied_fixes shape: `value` is the after when there is no diff `after`
    expect(rows[1].after).toBe('A bar chart of revenue')
    expect(effortLabel(rows[1])).toBe('~5 sec')                    // reviewing an auto fix is quick
  })

  it('auto-fix rows land in the Auto-fixed tab and resolve on acknowledgement', () => {
    const rows = autoFixRows(FIXES, (sc) => NAME[sc] || sc)
    expect(rows.every((r) => tabOf(r) === 'auto-fixed')).toBe(true)
    const acked = { [rows[0].id]: { state: 'accepted' } }
    expect(isResolved(rows[0], acked)).toBe(true)                  // ack marks it resolved (Resolved tab)
    expect(isResolved(rows[1], acked)).toBe(false)
  })
})
