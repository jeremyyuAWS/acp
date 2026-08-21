import { describe, it, expect } from 'vitest'
import { retentionSignal, retentionBucket, hasRetentionSignal, isAcceptable,
         RETENTION_BUCKETS } from './retentionSignal.js'
import { retentionOf } from './FileDrawer.jsx'

// A lifecycle recommendation is made, or it is not. It is never defaulted.
//
// THE DEFECT. retentionOf decided each row's badge from five fields, and four have zero backend
// references — `locked`, `tags`, `ageDays`, `views90d`. `undefined >= 540` is false, so on a real
// scan every branch fell through to the last line: "Keep — Active and in use". A constant, asserting
// a document is active and in use, rendered beside an "✓ accept" control and a bulk
// "Accept all recommendations" button.
//
// The bulk button is the part that mattered. One click recorded an accepted lifecycle decision for
// every document in the estate, over a recommendation nobody produced — and that record, not the
// badge, is what a later audit reads as "a person reviewed this and agreed".
//
// Meanwhile the REAL signal existed and was not being read: the discovery rule pass writes
// `lifecycle_status` with the rule id and reason, and mergeLifecycle already puts it on these rows.
// It reached DiscoveryResults' recommendations table and never the badge in front of the reviewer.

const real = (status, extra = {}) => ({ file: 'a.docx', lifecycle_status: status, ...extra })
const bare = (extra = {}) => ({ file: 'a.docx', name: 'a.docx', status: 'done', ...extra })

describe('what a REAL scan row produces', () => {
  it('is "Not assessed", never "Keep"', () => {
    // The shape get_scan returns: no lifecycle_status, no tags, no age, no usage.
    const r = retentionSignal(bare())
    expect(r.bucket).toBe('unassessed')
    expect(r.label).toBe('Not assessed')
    expect(r.source).toBe(null)
    // And it must not smuggle the old claim back in as prose.
    expect(r.why).not.toMatch(/active and in use/i)
    expect(r.why).toMatch(/no recommendation was produced/i)
  })

  it('cannot be accepted', () => {
    expect(isAcceptable(bare())).toBe(false)
    expect(hasRetentionSignal(bare())).toBe(false)
  })

  it('and retentionOf — the name every caller uses — agrees', () => {
    // SourceDrawer and sourceOps read retentionOf().label. If the delegation broke, they would
    // silently go back to reading "Keep" for every row.
    expect(retentionOf(bare()).label).toBe('Not assessed')
    expect(retentionOf(bare()).bucket).toBe('unassessed')
  })
})

describe('the REAL rule pass wins, and names itself', () => {
  it('reads an archive candidate off lifecycle_status', () => {
    const r = retentionSignal(real('Archive Candidate', { lifecycle_reason: "matched 'Legacy clinical policies'" }))
    expect(r.bucket).toBe('archive')
    expect(r.source).toBe('rule')
    expect(r.why).toContain("matched 'Legacy clinical policies'")
    // Never says the file WAS archived. The rule engine writes a status and one audit row.
    expect(r.why).toMatch(/nothing is moved/i)
  })

  it('reads a delete candidate, and denies that anything was trashed', () => {
    const r = retentionSignal(real('Delete Candidate', { lifecycle_rule_id: 'p42' }))
    expect(r.bucket).toBe('delete')
    expect(r.why).toContain('p42')
    expect(r.why).toMatch(/nothing is trashed/i)
  })

  it('treats a rule pass that matched nothing as a MEASURED Keep', () => {
    // The distinction discoveryRecommendations already draws: null and 'Active' are different
    // facts. One is a field nobody read; the other is a rule pass that ran and found nothing.
    const r = retentionSignal(real('Active'))
    expect(r.bucket).toBe('keep')
    expect(r.source).toBe('rule')
    expect(r.why).toMatch(/ran and matched nothing/i)
  })

  it('outranks the SIM heuristics', () => {
    // A real answer and a guess disagreeing must resolve to the real one, every time.
    const r = retentionSignal(real('Delete Candidate', { ageDays: 10, views90d: 900, superseded: false }))
    expect(r.bucket).toBe('delete')
  })
})

describe('unreadable outranks everything', () => {
  it('because a document nobody opened was assessed for nothing', () => {
    const r = retentionSignal({ locked: true, openIssue: 'password protected',
                                lifecycle_status: 'Delete Candidate' })
    expect(r.bucket).toBe('locked')
    expect(r.why).toContain('password protected')
  })
})

describe('the SIM heuristics still work, so the demo is unchanged', () => {
  it('legal-hold retains', () => {
    expect(retentionBucket({ tags: ['legal-hold'], ageDays: 9999, views90d: 0 })).toBe('retain')
  })

  it('superseded archives', () => {
    expect(retentionBucket({ superseded: true })).toBe('archive')
  })

  it('old and unused archives', () => {
    expect(retentionBucket({ ageDays: 600, views90d: 3, modifiedAge: '20 months ago' })).toBe('archive')
  })

  it('recent and used is a MEASURED keep', () => {
    const r = retentionSignal({ ageDays: 30, views90d: 400 })
    expect(r.bucket).toBe('keep')
    expect(r.source).toBe('signal')
  })

  it('but a HALF-present signal does not count as measured', () => {
    // ageDays with no views90d was the shape that made `undefined >= 540` decide an estate. Both or
    // neither — a threshold over one known and one missing value is a coin toss with a rationale.
    expect(retentionBucket({ ageDays: 600 })).toBe('unassessed')
    expect(retentionBucket({ views90d: 3 })).toBe('unassessed')
  })
})

describe('the bucket vocabulary', () => {
  it('every bucket a signal can produce is declared', () => {
    const produced = [
      retentionBucket(bare()), retentionBucket({ locked: true }),
      retentionBucket(real('Archive Candidate')), retentionBucket(real('Delete Candidate')),
      retentionBucket(real('Active')), retentionBucket({ tags: ['legal-hold'] }),
    ]
    for (const b of produced) expect(RETENTION_BUCKETS).toContain(b)
  })

  it('is not derived by parsing the label back out', () => {
    // Discover used to read the bucket off `label.startsWith('Archive')`, which made the badge TEXT
    // load-bearing: rewording it silently re-bucketed every row.
    const src = retentionSignal(real('Archive Candidate'))
    expect(src.bucket).toBe('archive')
    expect(src.label).toBe('Archive')
  })
})
