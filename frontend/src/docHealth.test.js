import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, 'FileDrawer.jsx'), 'utf8')

describe('Document Health header — the certify question first, from real counts only', () => {
  it('renders only for a document with findings, from the real issue/auto/review counts', () => {
    expect(src).toMatch(/issues\.length > 0 && st !== 'unanalysable'/)
    expect(src).toMatch(/const autoN = issues\.filter\(\(i\) => findingAuto\(i\)\)\.length/)
    expect(src).toMatch(/const pendingReviews = hitlItems\.reduce/)
  })

  it('states certify-readiness honestly for each state (applied / review / auto / blocked)', () => {
    expect(src).toMatch(/Fixes applied — re-validate to certify/)
    expect(src).toMatch(/Needs human review before it can be certified/)
    expect(src).toMatch(/Every blocking finding is auto-fixable/)
    expect(src).toMatch(/Blocked — needs remediation/)
  })

  it('one CTA opens the first pending review in place — no navigation away', () => {
    expect(src).toMatch(/⚖ Review now/)
    expect(src).toMatch(/setReviewSc\(scOfWcag\(hitlItems\[0\]\.rule_id\)/)
  })

  it('no fabricated effort/time estimate anywhere in the header (ADR 0016)', () => {
    // Check the CODE, not the comments (a comment legitimately says "nothing is estimated").
    const header = src.slice(src.indexOf('Document Health'), src.indexOf('drawerstats'))
      .split('\n').filter((l) => !l.trim().startsWith('//')).join('\n')
    expect(header).not.toMatch(/minutes|est\.|~\d|estimated/i)
  })
})
