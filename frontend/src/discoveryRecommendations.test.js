/**
 * The Discovery results numbers, as pure functions.
 *
 * These pin the four product rules the screen exists to keep, in the order they get broken:
 *   1. discovery RECOMMENDS — no bucket, label or tag says a file was archived or deleted;
 *   2. a missing answer is `null`, never a measured zero;
 *   3. every count carries its population, and buckets that partition sum to it;
 *   4. nothing is invented — an unrecorded rule or reason stays unrecorded.
 */
import { describe, it, expect } from 'vitest'
import {
  NOT_RECORDED, RECOMMENDATION_BUCKETS, acknowledgementSummary, estateSummary, formatBucketOf,
  hasLifecycleData, isConflicted, isUnreadable, lifecycleStatusOf, recommendationBucketOf,
  recommendationReconciliation, recommendationRows, reconcile, ruleNameOf, typeReconciliation,
  unreadableReasons,
} from './discoveryRecommendations.js'

const F = (file, extra = {}) => ({ file, type: file.split('.').pop().toUpperCase(), ...extra })
const arch = (file, rule = 'Legacy clinical policies') =>
  F(file, { lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
            lifecycle_reason: `matched archive rule '${rule}'` })
const del = (file, rule = 'Superseded drafts') =>
  F(file, { lifecycle_status: 'Delete Candidate', lifecycle_rule_id: 'p2',
            lifecycle_reason: `matched delete rule '${rule}'` })
const active = (file) => F(file, { lifecycle_status: 'Active' })

describe('format buckets mirror the backend estate taxonomy', () => {
  it('maps each supported format, image, a/v and everything else', () => {
    expect(formatBucketOf(F('a.docx'))).toBe('docx')
    expect(formatBucketOf(F('a.pdf'))).toBe('pdf')
    expect(formatBucketOf(F('a.xlsx'))).toBe('xlsx')
    expect(formatBucketOf(F('a.pptx'))).toBe('pptx')
    expect(formatBucketOf(F('a.htm'))).toBe('html')
    expect(formatBucketOf(F('a.PNG'))).toBe('image')
    expect(formatBucketOf(F('a.mp4'))).toBe('av')
    expect(formatBucketOf(F('a.zip'))).toBe('other')
    expect(formatBucketOf(F('no-extension'))).toBe('other')
  })

  it('every file lands in exactly one bucket, and the buckets sum to the population', () => {
    const files = [F('a.docx'), F('b.docx'), F('c.pdf'), F('d.png'), F('e.mp4'), F('f.zip')]
    const rec = typeReconciliation(files)
    expect(rec.total).toBe(6)
    expect(rec.sum).toBe(6)
    expect(rec.balanced).toBe(true)
    expect(rec.population).toBe('files discovered')
    // The sum is the assertion, but so is the shape: no file may be counted twice.
    expect(rec.buckets.reduce((a, b) => a + b.count, 0)).toBe(files.length)
  })

  it('is null when there are no rows to count — not an empty table of zeros', () => {
    expect(typeReconciliation(null)).toBeNull()
    expect(typeReconciliation(undefined)).toBeNull()
  })

  it('keeps types that carry no WCAG test visible, flagged rather than dropped', () => {
    const rec = typeReconciliation([F('a.png'), F('b.mp4'), F('c.docx')])
    const keys = rec.buckets.map((b) => b.key)
    expect(keys).toContain('image')
    expect(keys).toContain('av')
    expect(rec.buckets.find((b) => b.key === 'image').assessable).toBe(false)
    expect(rec.buckets.find((b) => b.key === 'docx').assessable).toBe(true)
  })
})

describe('a missing lifecycle answer is absent, never zero', () => {
  it('hasLifecycleData is false when no row carries the column', () => {
    expect(hasLifecycleData([F('a.docx'), F('b.pdf')])).toBe(false)
    expect(hasLifecycleData(null)).toBe(false)
  })

  it("distinguishes 'no field' from a rule pass that matched nothing", () => {
    expect(lifecycleStatusOf(F('a.docx'))).toBeNull()
    expect(lifecycleStatusOf(active('a.docx'))).toBe('Active')
    expect(hasLifecycleData([active('a.docx')])).toBe(true)
  })

  it('withholds the archive/deletion headline entirely when the column never arrived', () => {
    const s = estateSummary([F('a.docx'), F('b.pdf')])
    expect(s.discovered).toBe(2)
    expect(s.archive).toBeNull()      // NOT 0
    expect(s.delete).toBeNull()       // NOT 0
    expect(s.hasLifecycle).toBe(false)
  })

  it('reports a real zero once the column IS present', () => {
    const s = estateSummary([active('a.docx'), active('b.pdf')])
    expect(s.archive).toBe(0)
    expect(s.delete).toBe(0)
    expect(s.hasLifecycle).toBe(true)
  })

  it('returns no summary at all when nothing was read', () => {
    expect(estateSummary(null)).toBeNull()
  })

  it('omits the recommendation table and reconciliation without the column', () => {
    expect(recommendationRows([F('a.docx')])).toBeNull()
    expect(recommendationReconciliation([F('a.docx')])).toBeNull()
    expect(acknowledgementSummary([F('a.docx')])).toBeNull()
  })
})

describe('discovery recommends — it never reports an action it did not take', () => {
  it('labels every bucket as a review outcome, and no bucket claims a completed action', () => {
    const labels = RECOMMENDATION_BUCKETS.map(([, label]) => label.toLowerCase())
    labels.forEach((l) => {
      expect(l).not.toMatch(/\barchived\b(?! by an approved rule)/)
      expect(l).not.toMatch(/\bdeleted\b/)
      expect(l).not.toMatch(/\btrashed\b/)
    })
    expect(labels).toContain('tagged for archive review')
    expect(labels).toContain('tagged for deletion review')
  })

  it('keeps an executed Archived/Deleted file out of the "tagged for review" buckets', () => {
    expect(recommendationBucketOf(F('a.docx', { lifecycle_status: 'Archived' }))).toBe('actioned')
    expect(recommendationBucketOf(F('b.docx', { lifecycle_status: 'Deleted' }))).toBe('actioned')
    expect(recommendationBucketOf(arch('c.docx'))).toBe('archive')
    expect(recommendationBucketOf(del('d.docx'))).toBe('delete')
  })

  it('exempt and unreadable files get their own buckets, unreadable winning', () => {
    expect(recommendationBucketOf(F('a.docx', { lifecycle_status: 'Exempted' }))).toBe('exempt')
    expect(recommendationBucketOf(F('b.docx', { locked: true, lifecycle_status: 'Archive Candidate' }))).toBe('unreadable')
    expect(recommendationBucketOf(F('c.docx', { status: 'error', lifecycle_status: 'Archive Candidate' }))).toBe('unreadable')
  })
})

describe('the reconciliation partitions the estate', () => {
  const files = [
    arch('Clinical/2019/sepsis.docx'), arch('Clinical/2020/triage.pdf'),
    del('Program/_superseded/alt-text.docx'),
    active('Program/live.docx'), active('Program/live2.pdf'),
    F('locked.pdf', { locked: true, openIssue: 'password-protected', lifecycle_status: 'Active' }),
  ]

  it('puts every discovered file in exactly one bucket, summing to the total', () => {
    const rec = recommendationReconciliation(files)
    expect(rec.total).toBe(6)
    expect(rec.sum).toBe(6)
    expect(rec.balanced).toBe(true)
    const by = Object.fromEntries(rec.buckets.map((b) => [b.key, b.count]))
    expect(by.archive).toBe(2)
    expect(by.delete).toBe(1)
    expect(by.none).toBe(2)
    expect(by.unreadable).toBe(1)
  })

  it('always shows archive / deletion / no-recommendation, zero or not', () => {
    const rec = recommendationReconciliation([active('a.docx')])
    const keys = rec.buckets.map((b) => b.key)
    expect(keys).toEqual(expect.arrayContaining(['archive', 'delete', 'none']))
    expect(rec.buckets.find((b) => b.key === 'archive').count).toBe(0)
    // A state that did not occur is not a row of this population.
    expect(keys).not.toContain('exempt')
  })

  it('flags an unbalanced reconciliation instead of hiding it', () => {
    const bad = reconcile([{ key: 'a', count: 2 }], 3, 'files discovered')
    expect(bad.balanced).toBe(false)
    expect(bad.sum).toBe(2)
    expect(bad.total).toBe(3)
  })
})

describe('the recommendation table names the rule that produced each tag', () => {
  it('joins the policy list on lifecycle_rule_id', () => {
    const row = arch('a.docx')
    expect(ruleNameOf(row, [{ policy_id: 'p1', name: 'Legacy clinical policies' }]))
      .toBe('Legacy clinical policies')
  })

  it("falls back to the name the backend quoted into its own recorded reason", () => {
    expect(ruleNameOf(arch('a.docx', 'Legacy clinical policies'), null))
      .toBe('Legacy clinical policies')
  })

  it('returns null rather than guessing a name from the action', () => {
    expect(ruleNameOf(F('a.docx', { lifecycle_status: 'Archive Candidate' }), null)).toBeNull()
  })

  it('lists deletion recommendations before archive ones, with the recorded reason verbatim', () => {
    const rows = recommendationRows([arch('a.docx'), del('z.docx')], null)
    expect(rows.map((r) => r.bucket)).toEqual(['delete', 'archive'])
    expect(rows[0].tag).toBe('deletion review')
    expect(rows[1].tag).toBe('archive review')
    expect(rows[1].reason).toBe("matched archive rule 'Legacy clinical policies'")
  })

  it('marks the conflict the backend resolved by keeping the safer recommendation', () => {
    const row = F('a.docx', {
      lifecycle_status: 'Archive Candidate',
      lifecycle_reason: "matched archive rule 'Legacy' — flagged for review: delete rule 'Superseded' also matched but its override is not permitted",
    })
    expect(isConflicted(row)).toBe(true)
    expect(recommendationRows([row])[0].conflicted).toBe(true)
    // The SAFER recommendation is what is shown — never the delete rule that lost.
    expect(recommendationRows([row])[0].bucket).toBe('archive')
  })
})

describe('could-not-be-read reasons are recorded, never guessed', () => {
  it('buckets recorded reasons and sums them to the unreadable count', () => {
    const files = [
      F('a.pdf', { locked: true, openIssue: 'Permission denied' }),
      F('b.pdf', { locked: true, openIssue: 'Permission denied' }),
      F('c.pdf', { status: 'error', openIssue: 'Checked out / locked' }),
      F('d.pdf'),
    ]
    const r = unreadableReasons(files)
    expect(r.total).toBe(3)
    expect(r.sum).toBe(3)
    expect(r.balanced).toBe(true)
    expect(r.buckets[0]).toMatchObject({ reason: 'Permission denied', count: 2, recorded: true })
  })

  it('counts a file with no recorded reason as exactly that, keeping the sum honest', () => {
    const r = unreadableReasons([F('a.pdf', { locked: true })])
    expect(r.buckets).toEqual([{ reason: NOT_RECORDED, count: 1, recorded: false }])
    expect(r.balanced).toBe(true)
  })

  it('is null with no rows, and a measured zero with rows and no failures', () => {
    expect(unreadableReasons(null)).toBeNull()
    expect(unreadableReasons([F('a.pdf')]).total).toBe(0)
  })

  it('accepts a caller-supplied reason lookup (the scan.file_error decision log)', () => {
    const files = [F('a.pdf', { status: 'error' })]
    const r = unreadableReasons(files, (row) => (row.file === 'a.pdf' ? 'HttpError 403' : null))
    expect(r.buckets[0].reason).toBe('HttpError 403')
  })

  it('treats a real scan error row as unreadable, not only the SIM locked flag', () => {
    expect(isUnreadable(F('a.pdf', { status: 'error' }))).toBe(true)
    expect(isUnreadable(F('a.pdf', { locked: true }))).toBe(true)
    expect(isUnreadable(F('a.pdf'))).toBe(false)
  })
})

describe('the acknowledgement covers exactly what is on screen', () => {
  it('counts both review buckets and the overrides', () => {
    const ack = acknowledgementSummary([arch('a.docx'), arch('b.pdf'), del('c.docx')], ['a.docx'])
    expect(ack).toEqual({ total: 3, archive: 2, delete: 1, overridden: 1 })
  })

  it('is absent when the rules matched nothing — there is nothing to approve', () => {
    expect(acknowledgementSummary([active('a.docx')])).toBeNull()
  })
})

describe('the estate summary states the population it counts over', () => {
  it('carries the whole-estate listing total separately from the rows on screen', () => {
    const s = estateSummary([F('a.docx')], { discovered: 12408, truncated: false })
    expect(s.discovered).toBe(1)
    expect(s.estateListed).toBe(12408)
  })

  it('propagates truncation, so a floor is never presented as a total', () => {
    expect(estateSummary([F('a.docx')], { discovered: 1, truncated: true }).truncated).toBe(true)
    expect(estateSummary([F('a.docx')], null).truncated).toBe(false)
  })
})
