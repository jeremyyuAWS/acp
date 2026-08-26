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
  NOT_RECORDED, RECOMMENDATION_BUCKETS, acknowledgementSummary, estateSummary,
  estateTypeReconciliation, formatBucketOf,
  hasLifecycleData, isConflicted, isUnreadable, lifecycleStatusOf, overrideOf, recommendationBucketOf,
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

describe('estateTypeReconciliation — the whole-estate version, image/video included', () => {
  it('counts over the estate inventory, not the scanned rows — the gap typeReconciliation cannot close', () => {
    // A realistic estate where almost nothing is a scannable format: typeReconciliation(files)
    // would only ever see the 3 docx rows that got opened and scored, reporting the 9,000 images
    // as if they did not exist. estateTypeReconciliation reads the SAME denominator the "N files
    // discovered" headline already uses (inventory.discovered), so the two numbers agree.
    const inventory = { discovered: 9003, by_format: { docx: 3, image: 9000 } }
    const rec = estateTypeReconciliation(inventory)
    expect(rec.total).toBe(9003)
    expect(rec.sum).toBe(9003)
    expect(rec.balanced).toBe(true)
    expect(rec.population).toBe('the whole estate listing')
    const image = rec.buckets.find((b) => b.key === 'image')
    expect(image.count).toBe(9000)
    expect(image.assessable).toBe(false)
  })

  it('is null without a usable inventory — the caller falls back to typeReconciliation(files)', () => {
    expect(estateTypeReconciliation(null)).toBeNull()
    expect(estateTypeReconciliation(undefined)).toBeNull()
    expect(estateTypeReconciliation({})).toBeNull()                          // no by_format at all
    expect(estateTypeReconciliation({ discovered: 12 })).toBeNull()          // discovered, no by_format
    expect(estateTypeReconciliation({ by_format: { docx: 1 } })).toBeNull()  // by_format, no discovered
  })

  it('drops a format bucket with zero files — not a bucket of this estate', () => {
    const rec = estateTypeReconciliation({ discovered: 2, by_format: { docx: 2, image: 0, av: 0 } })
    expect(rec.buckets.map((b) => b.key)).toEqual(['docx'])
  })

  it('flags an unbalanced inventory rather than silently absorbing the gap', () => {
    // by_format undercounting discovered — e.g. a format bucket this taxonomy does not (yet) name.
    const rec = estateTypeReconciliation({ discovered: 10, by_format: { docx: 4 } })
    expect(rec.balanced).toBe(false)
    expect(rec.sum).toBe(4)
    expect(rec.total).toBe(10)
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

  // Found live 2026-08-26: a fresh Discover-only scan (ADR 0020 defers analysis to Assess) has
  // zero assessed rows by construction, every time — not a real "0 files discovered". The page
  // header correctly showed "6,922 documents discovered" while this screen's own headline stat
  // read "0 files discovered", for a scan that had never been assessed.
  it('falls back to estateListed when files is empty and the whole-estate total is known', () => {
    const s = estateSummary([], { discovered: 6922 })
    expect(s.discovered).toBe(6922)
    expect(s.estateListed).toBe(6922)
  })

  it('does not fall back when files has real (even partial) rows — a genuinely scoped view stays scoped', () => {
    const s = estateSummary([F('a.docx')], { discovered: 6922 })
    expect(s.discovered).toBe(1)
    expect(s.estateListed).toBe(6922)
  })

  it('stays 0 when files is empty and there is no inventory total to fall back to', () => {
    const s = estateSummary([], null)
    expect(s.discovered).toBe(0)
    expect(s.estateListed).toBeNull()
  })

  it('archive/delete/hasLifecycle stay absent (not falsely zeroed) in the empty-files fallback case', () => {
    // hasLifecycleData([]) is false — the lifecycle columns cannot have reached an empty row set,
    // so archive/delete must still read null, not 0, even though `discovered` now reads 6922.
    const s = estateSummary([], { discovered: 6922 })
    expect(s.archive).toBeNull()
    expect(s.delete).toBeNull()
    expect(s.hasLifecycle).toBe(false)
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

  it('sorts a file with NO lifecycle record into its own bucket, not "no recommendation"', () => {
    // The partial-join case: the inventory read covered some files and not others. Calling the
    // uncovered ones "no recommendation" would report an unread file as a checked one — and it
    // would still add up, which is what makes it dangerous.
    const mixed = [arch('tagged.docx'), { file: 'unlisted.pdf', type: 'PDF' }]
    expect(recommendationBucketOf(mixed[1])).toBe('unknown')
    const rec = recommendationReconciliation(mixed)
    const by = Object.fromEntries(rec.buckets.map((b) => [b.key, b.count]))
    expect(by.unknown).toBe(1)
    expect(by.none).toBe(0)
    expect(rec.balanced).toBe(true)
    expect(rec.sum).toBe(2)
  })

  it('only claims "no recommendation" for a status the record actually holds', () => {
    expect(recommendationBucketOf(active('a.docx'))).toBe('none')
    expect(recommendationBucketOf(F('a.docx', { lifecycle_status: 'Failed' }))).toBe('none')
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

describe('a recorded override (lifecycle rules #8) rides alongside the recommendation', () => {
  it('is null when no override reason was recorded', () => {
    expect(overrideOf(arch('a.docx'))).toBeNull()
    expect(overrideOf(F('a.docx', { lifecycle_override_reason: '   ' }))).toBeNull()   // blank, not real
    expect(overrideOf(null)).toBeNull()
  })

  it('carries the reason, actor and timestamp when one was recorded', () => {
    const row = F('a.docx', {
      lifecycle_override_reason: 'under active legal hold',
      lifecycle_overridden_by: 'reviewer@x.com',
      lifecycle_overridden_at: '2026-08-21T10:00:00+00:00',
    })
    expect(overrideOf(row)).toEqual({
      reason: 'under active legal hold', actor: 'reviewer@x.com', at: '2026-08-21T10:00:00+00:00',
    })
  })

  it('reaches recommendationRows() so the table can render it per-file', () => {
    const overridden = F('a.docx', {
      lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
      lifecycle_reason: "matched archive rule 'Legacy'",
      lifecycle_override_reason: 'still in active use', lifecycle_overridden_by: 'reviewer@x.com',
    })
    const rows = recommendationRows([overridden, arch('b.docx')])
    expect(rows.find((r) => r.file === 'a.docx').override).toEqual({
      reason: 'still in active use', actor: 'reviewer@x.com', at: null,
    })
    expect(rows.find((r) => r.file === 'b.docx').override).toBeNull()
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
