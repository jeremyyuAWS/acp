import { describe, it, expect } from 'vitest'
import {
  clusterKeyOf, clusterRows, clusterOfFinding, batchTargetsOf, CLUSTER_ACTIONABLE_LANES,
} from './remediationClusters.js'
import { LANES } from './remediationInboxModel.js'

// An AI-drafted (apply-lane) 1.1.1 finding in a .docx — the shape the 265-row production run was
// mostly made of. Overrides give every other lane/criterion/format used below.
const f = (id, over = {}) => ({
  id,
  file: `Doc-${id}.docx`,
  rule_id: '1.1.1',
  title: 'DOCX · Image needs alt text',
  severity: 'SERIOUS',
  hasProposal: true,
  after: 'A bar chart of revenue',
  ...over,
})

const AUTO = { hasProposal: false, after: null, autoApplied: true }              // review lane
const MANUAL = { hasProposal: false, after: null }                               // manual lane
const BLOCKED = { status: 'blocked' }                                            // blocked lane
const HANDOFF = { rejectedFix: true }                                            // handoff lane
const RECHECK = { status: 'recheck' }                                            // recheck lane

const keysOf = (rows) => rows.map((r) => r.key)
const typesOf = (rows) => rows.map((r) => r.type)
const idsOf = (list) => list.map((x) => x.id)

describe('clusterKeyOf — criterion + lane, and nothing else', () => {
  it('composes the two facts that make two findings the same decision', () => {
    expect(clusterKeyOf(f(1))).toBe('1.1.1|apply')
    expect(clusterKeyOf(f(2, { ...AUTO }))).toBe('1.1.1|review')
  })

  it('normalises every spelling of a criterion id', () => {
    expect(clusterKeyOf(f(1, { rule_id: 'SC_1_1_1' }))).toBe('1.1.1|apply')
    expect(clusterKeyOf(f(1, { rule_id: undefined, ruleId: 'WCAG_1.1.1' }))).toBe('1.1.1|apply')
    expect(clusterKeyOf(f(1, { rule_id: undefined, wcag: '1.1.1' }))).toBe('1.1.1|apply')
  })

  it('returns null when the criterion cannot be determined — never cluster on a guess', () => {
    expect(clusterKeyOf(f(1, { rule_id: null }))).toBeNull()
    expect(clusterKeyOf(f(1, { rule_id: '' }))).toBeNull()
    expect(clusterKeyOf(f(1, { rule_id: 'color-contrast' }))).toBeNull()  // an axe rule name is not an SC
    expect(clusterKeyOf(null)).toBeNull()
  })

  it('FORMAT is NOT in the key: the same criterion and lane in .docx and .pdf IS one decision', () => {
    // A DELIBERATE RELAXATION OF TIER C, not an oversight. Keying on format was implemented and then
    // reverted (2026-09-01) at the product owner's direction: it split the large single-criterion
    // runs this module exists to collapse — the 265-finding alt-text backlog, spread over .docx,
    // .pdf and .pptx, became three queues to work instead of one — and the reviewer's question about
    // such a group ("is ACP's alt-text drafting trustworthy here") was judged not to be a per-format
    // one. The compensating control is DISCLOSURE, asserted below and pinned in its own test: the
    // row states the formats it spans instead of quietly spanning them.
    expect(clusterKeyOf(f(1, { file: 'a.docx' }))).toBe(clusterKeyOf(f(2, { file: 'a.pdf' })))
    const rows = clusterRows([f(1, { file: 'a.docx' }), f(2, { file: 'a.pdf' })])
    expect(rows).toHaveLength(1)
    expect(rows[0].formats).toEqual(['docx', 'pdf'])   // …and the reviewer is told, on the row
  })

  it('SEVERITY is NOT part of the key: it would fragment exactly the clusters we want', () => {
    expect(clusterKeyOf(f(1, { severity: 'CRITICAL' })))
      .toBe(clusterKeyOf(f(2, { severity: null, file: 'Other.docx' })))
  })

  it('page and filename are not part of the key — the cluster spans documents by design', () => {
    expect(clusterKeyOf(f(1, { file: 'A.docx', page: 2 })))
      .toBe(clusterKeyOf(f(2, { file: 'Z.docx', page: 41 })))
  })
})

describe('clusterRows — what actually collapses', () => {
  it('three 1.1.1 findings cluster across .docx and .pdf — one criterion, one queue', () => {
    // This is the reversal made concrete: the .pdf finding used to be stranded as a single row.
    const rows = clusterRows([f(1), f(2), f(3, { file: 'Policy.pdf', title: 'PDF · Image needs alt text' })])
    expect(typesOf(rows)).toEqual(['cluster'])
    expect(rows[0].count).toBe(3)
    expect(idsOf(rows[0].items)).toEqual([1, 2, 3])
    expect(rows[0].formats).toEqual(['docx', 'pdf'])
    expect(rows[0].fileCount).toBe(3)
  })

  it('a 1.1.1 and a 2.4.2 never cluster', () => {
    const rows = clusterRows([f(1), f(2, { rule_id: '2.4.2', title: 'DOCX · Document has no title' })])
    expect(typesOf(rows)).toEqual(['single', 'single'])
    expect(idsOf(rows.map((r) => r.finding))).toEqual([1, 2])
  })

  it('LANE still splits: an auto-applied fix and an AI draft in the SAME file are two clusters', () => {
    // Lane is now doing more of the work, since format no longer splits anything. Different lanes
    // are different decisions: one asks "is this drafted value right?", the other "did the change
    // ACP already made land correctly?". A single approval cannot mean both — same criterion, same
    // document, same format notwithstanding.
    const SAME = { file: 'Shared.docx' }
    const rows = clusterRows([f(1, SAME), f(2, SAME), f(3, { ...SAME, ...AUTO }), f(4, { ...SAME, ...AUTO })])
    expect(typesOf(rows)).toEqual(['cluster', 'cluster'])
    expect(keysOf(rows)).toEqual(['1.1.1|apply', '1.1.1|review'])
    expect(rows[0].laneKey).toBe('apply')
    expect(rows[1].laneKey).toBe('review')
    expect(rows[0].lane).toBe(LANES.apply)
    expect(idsOf(rows[0].items)).toEqual([1, 2])
    expect(idsOf(rows[1].items)).toEqual([3, 4])
  })

  it('a group appears at the position of its FIRST member, and order is otherwise preserved', () => {
    const input = [
      f(10, { rule_id: '2.4.2' }),             // single (only one 2.4.2)
      f(11),                                    // first 1.1.1 → the cluster sits here
      f(12, { rule_id: '1.3.1' }),             // single
      f(13),                                    // joins the cluster above
      f(14, { file: 'Late.pdf' }),             // also joins it now — format no longer separates
    ]
    const rows = clusterRows(input)
    expect(keysOf(rows)).toEqual(['single:10', '1.1.1|apply', 'single:12'])
    expect(idsOf(rows[1].items)).toEqual([11, 13, 14])  // members keep input order inside the cluster
    expect(rows[1].formats).toEqual(['docx', 'pdf'])    // …and the late .pdf is disclosed, not hidden
  })

  it('is stable: the same input yields the same rows, and reordering the input reorders the rows', () => {
    const input = [f(1), f(2, { rule_id: '2.4.2' }), f(3)]
    expect(keysOf(clusterRows(input))).toEqual(keysOf(clusterRows(input)))
    expect(keysOf(clusterRows(input))).toEqual(['1.1.1|apply', 'single:2'])
    expect(keysOf(clusterRows([...input].reverse())))
      .toEqual(['1.1.1|apply', 'single:2'])     // f(3) now leads the cluster
  })

  it('a group below minSize emits one single per member, in order — never a cluster of one', () => {
    const rows = clusterRows([f(1)])
    expect(typesOf(rows)).toEqual(['single'])
    expect(rows[0].key).toBe('single:1')

    // minSize 3: the pair of 1.1.1s is no longer worth a grouped decision, so both are singles.
    const three = clusterRows([f(1), f(2), f(3, { rule_id: '2.4.2' })], {}, { minSize: 3 })
    expect(typesOf(three)).toEqual(['single', 'single', 'single'])
    expect(idsOf(three.map((r) => r.finding))).toEqual([1, 2, 3])

    // ...and at minSize 2 (the default) the same input does cluster.
    expect(clusterRows([f(1), f(2), f(3, { rule_id: '2.4.2' })], {}, { minSize: 2 })[0].type).toBe('cluster')
  })

  it('findings with no determinable criterion are always singles, even several of them', () => {
    const rows = clusterRows([f(1, { rule_id: null }), f(2, { rule_id: null }), f(3, { rule_id: '' })])
    expect(typesOf(rows)).toEqual(['single', 'single', 'single'])
  })

  it('an empty queue returns no rows', () => {
    expect(clusterRows([])).toEqual([])
    expect(clusterRows([], { 1: { state: 'accepted' } }, { minSize: 1 })).toEqual([])
  })

  it('counts documents, not findings — the number that turns 265 rows into one', () => {
    const rows = clusterRows([f(1, { file: 'A.docx' }), f(2, { file: 'B.docx' }), f(3, { file: 'A.docx' })])
    expect(rows[0].count).toBe(3)
    expect(rows[0].files).toEqual(['A.docx', 'B.docx'])   // distinct, first-appearance order
    expect(rows[0].fileCount).toBe(2)
  })
})

describe('formats — the disclosure that pays for dropping format from the key', () => {
  it('reports every format the cluster spans, in first-appearance order, deduplicated', () => {
    // This is the compensating control for the Tier C relaxation. A reviewer approving this pattern
    // is approving it across three formats, and the row is what tells them so — on the row and in
    // the batch confirmation. If this collapses to one format the breadth of the decision becomes
    // invisible, which is the failure the whole module exists to prevent.
    const row = clusterRows([
      f(1, { file: 'Brief.docx' }),
      f(2, { file: 'Policy.pdf' }),
      f(3, { file: 'Notes.docx' }),   // duplicate format — must not appear twice
      f(4, { file: 'Deck.pptx' }),
    ])[0]
    expect(row.formats).toEqual(['docx', 'pdf', 'pptx'])
    expect(row.count).toBe(4)
    expect(row.fileCount).toBe(4)     // four documents, three formats — both facts are stated
  })

  it('a single-format cluster still reports its one format, as an array', () => {
    const row = clusterRows([f(1), f(2)])[0]
    expect(row.formats).toEqual(['docx'])
  })

  it('a finding with no filename contributes no format rather than an empty one', () => {
    const row = clusterRows([f(1, { file: 'Brief.docx' }), f(2, { file: '' }), f(3, { file: null })])[0]
    expect(row.formats).toEqual(['docx'])
    expect(row.count).toBe(3)         // it is still a member and still gets decided
    expect(row.fileCount).toBe(1)
  })
})

describe('the representative — the member the reviewer actually looks at', () => {
  it('is the first UNRESOLVED member, and its wording is the row wording', () => {
    const items = [
      f(1, { title: 'DOCX · Chart image needs alt text' }),
      f(2, { title: 'DOCX · Logo image needs alt text' }),
    ]
    expect(clusterRows(items)[0].representativeId).toBe(1)
    expect(clusterRows(items)[0].issue).toBe('Chart image needs alt text')

    // With #1 decided, the row must speak for #2 — not keep quoting a finding already handled.
    const after = clusterRows(items, { 1: { state: 'accepted' } })[0]
    expect(after.representativeId).toBe(2)
    expect(after.issue).toBe('Logo image needs alt text')
  })

  it('walks forward as decisions accumulate, and never goes null', () => {
    const items = [f(1), f(2), f(3)]
    const dec = {}
    expect(clusterRows(items, dec)[0].representativeId).toBe(1)
    dec[1] = { state: 'accepted' }
    expect(clusterRows(items, dec)[0].representativeId).toBe(2)
    dec[2] = { state: 'rejected' }
    expect(clusterRows(items, dec)[0].representativeId).toBe(3)
    dec[3] = { state: 'not_applicable' }
    const done = clusterRows(items, dec)[0]
    expect(done.representativeId).toBe(1)          // all resolved → falls back to the first member
    expect(done.representativeId).not.toBeNull()
    expect(done.unresolved).toEqual([])
    expect(done.resolvedCount).toBe(3)
  })

  it('reports resolved / unresolved membership alongside the total', () => {
    const row = clusterRows([f(1), f(2), f(3)], { 2: { state: 'accepted' } })[0]
    expect(row.count).toBe(3)
    expect(row.resolvedCount).toBe(1)
    expect(idsOf(row.unresolved)).toEqual([1, 3])
    expect(idsOf(row.items)).toEqual([1, 2, 3])    // items is every member, decided or not
  })
})

describe('severity mix — kept out of the key, shown on the row', () => {
  it('reports the mix worst-first, counts an unrated finding, and omits zero buckets', () => {
    const row = clusterRows([
      f(1, { severity: 'SERIOUS' }),
      f(2, { severity: 'CRITICAL' }),
      f(3, { severity: null }),
      f(4, { severity: 'SERIOUS' }),
    ])[0]
    expect(row.severities).toEqual({ CRITICAL: 1, SERIOUS: 2, UNRATED: 1 })
    expect(Object.keys(row.severities)).toEqual(['CRITICAL', 'SERIOUS', 'UNRATED'])  // worst first
    expect(row.severities.MODERATE).toBeUndefined()                                   // no zero buckets
    // The mix always accounts for every member — a reviewer can trust it as the whole cluster.
    expect(Object.values(row.severities).reduce((a, b) => a + b, 0)).toBe(row.count)
  })

  it('a mixed-severity group is still ONE cluster', () => {
    const rows = clusterRows([f(1, { severity: 'CRITICAL' }), f(2, { severity: 'MINOR' })])
    expect(rows).toHaveLength(1)
    expect(rows[0].count).toBe(2)
  })
})

describe('batchTargetsOf — the exact scope of a grouped decision', () => {
  it('names the three actionable lanes and no others', () => {
    expect([...CLUSTER_ACTIONABLE_LANES].sort()).toEqual(['apply', 'recheck', 'review'])
    for (const k of ['manual', 'handoff', 'blocked']) expect(CLUSTER_ACTIONABLE_LANES.has(k)).toBe(false)
  })

  it('is every unresolved member of an actionable cluster', () => {
    const rows = clusterRows([f(1), f(2), f(3)])
    expect(idsOf(batchTargetsOf(rows[0], {}))).toEqual([1, 2, 3])
  })

  it('reaches across formats, exactly as the cluster does — no wider, no narrower', () => {
    // The batch and the disclosed cluster must be the same set. If `formats` says .docx and .pdf,
    // the decision lands on both; there is no hidden narrowing to the representative's format.
    const row = clusterRows([f(1, { file: 'A.docx' }), f(2, { file: 'B.pdf' }), f(3, { file: 'C.pptx' })])[0]
    expect(row.formats).toEqual(['docx', 'pdf', 'pptx'])
    expect(idsOf(batchTargetsOf(row, {}))).toEqual([1, 2, 3])
  })

  it('EXCLUDES members that are already decided', () => {
    const items = [f(1), f(2), f(3)]
    const dec = { 2: { state: 'accepted' }, 3: { state: 'rejected' } }
    const row = clusterRows(items, dec)[0]
    expect(idsOf(batchTargetsOf(row, dec))).toEqual([1])
    // Re-evaluated against the decisions passed in, not the snapshot the row was built with:
    // a batch armed before an individual approval must not re-decide it.
    expect(idsOf(batchTargetsOf(clusterRows(items)[0], dec))).toEqual([1])
  })

  it('EXCLUDES a member resolved by its own status, with no recorded decision', () => {
    const row = clusterRows([f(1), f(2, { status: 'approved' }), f(3)])[0]
    expect(idsOf(batchTargetsOf(row, {}))).toEqual([1, 3])
  })

  it('reaches nothing in the manual, handoff and blocked lanes', () => {
    for (const over of [MANUAL, HANDOFF, BLOCKED]) {
      const rows = clusterRows([f(1, over), f(2, over)])
      expect(rows[0].type).toBe('cluster')            // they still cluster for display…
      expect(batchTargetsOf(rows[0], {})).toEqual([]) // …but no batch decision may touch them
    }
  })

  it('reaches nothing from a single row', () => {
    const rows = clusterRows([f(1), f(2, { rule_id: '2.4.2' })])
    expect(rows.every((r) => r.type === 'single')).toBe(true)
    expect(batchTargetsOf(rows[0], {})).toEqual([])
    expect(batchTargetsOf(null, {})).toEqual([])
    expect(batchTargetsOf(undefined)).toEqual([])
  })

  it('drops a non-actionable member even from a hand-assembled row', () => {
    // The lane is in the key, so a real cluster is single-laned. The per-member guard is what makes
    // "manual, handoff and blocked are never in a batch" true regardless of how the row was built.
    const row = { ...clusterRows([f(1), f(2)])[0], items: [f(1), f(2, MANUAL), f(3, BLOCKED), f(4, HANDOFF)] }
    expect(idsOf(batchTargetsOf(row, {}))).toEqual([1])
  })

  it('includes the recheck lane', () => {
    const rows = clusterRows([f(1, RECHECK), f(2, RECHECK)])
    expect(rows[0].laneKey).toBe('recheck')
    expect(idsOf(batchTargetsOf(rows[0], {}))).toEqual([1, 2])
  })
})

describe('clusterOfFinding', () => {
  const rows = clusterRows([f(1), f(2), f(3, { rule_id: '2.4.2' })])

  it('finds the cluster a member belongs to', () => {
    expect(clusterOfFinding(rows, 1)).toBe(rows[0])
    expect(clusterOfFinding(rows, 2)).toBe(rows[0])
  })

  it('finds a single row by its finding id', () => {
    expect(clusterOfFinding(rows, 3)).toBe(rows[1])
    expect(clusterOfFinding(rows, 3).type).toBe('single')
  })

  it('finds a member that joined the cluster from another format', () => {
    const mixed = clusterRows([f(1, { file: 'A.docx' }), f(2, { file: 'B.pdf' })])
    expect(clusterOfFinding(mixed, 2)).toBe(mixed[0])
    expect(clusterOfFinding(mixed, 2).formats).toEqual(['docx', 'pdf'])
  })

  it('returns null for an id that is not in the queue', () => {
    expect(clusterOfFinding(rows, 99)).toBeNull()
    expect(clusterOfFinding([], 1)).toBeNull()
    expect(clusterOfFinding(null, 1)).toBeNull()
  })
})
