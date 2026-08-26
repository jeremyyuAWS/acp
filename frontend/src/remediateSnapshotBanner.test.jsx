import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The snapshot-separation banner on the Remediate tab.
//
// Problem (2026-08-22): when a new assessment runs while prior remediation results are on screen,
// the page shows two snapshots at once — live scan progress ("Assessing 0 of 148") alongside
// stale remediation counts ("720 Drafted", "341 documents processed") from the prior assessment.
// A user cannot tell which figures belong together.
//
// Fix: when run.status is not a finished state AND files.length > 0 (prior results exist), show
// a persistent amber banner: "A new assessment is running — results below are from [date]."
// Two actions: navigate to Assess to watch progress, or dismiss and continue working from old data.
//
// The banner state resets when the scan changes (runId changes), so a user who dismissed it on
// scan A does not see a stale dismissal on scan B.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Strip JSX comments before structural assertions (a comment quoting deleted code is not code).
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('Remediate snapshot-separation banner', () => {
  const src = () => code('Remediate.jsx')

  it('defines the finished-state set used to derive assessRunning', () => {
    const s = src()
    // All seven end states must appear in the set so a partial list cannot classify a running scan
    // as finished. Cancelled/interrupted/superseded are also "not running" from the user's
    // perspective — superseded is a run the single-flight guard auto-killed (api/store.py
    // supersede_scan) to make way for a newer scan, same as an explicit stop from here on.
    expect(s).toMatch(/_DONE_STATES/)
    expect(s).toMatch(/'done'/)
    expect(s).toMatch(/'complete'/)
    expect(s).toMatch(/'completed'/)
    expect(s).toMatch(/'finalized'/)
    expect(s).toMatch(/'cancelled'/)
    expect(s).toMatch(/'interrupted'/)
    expect(s).toMatch(/'superseded'/)
  })

  it('derives assessRunning from run.status against the finished-state set', () => {
    const s = src()
    // The banner must gate on status, not on a hardcoded string, so adding a new terminal state
    // to _DONE_STATES is the only change needed when the backend gains one.
    expect(s).toMatch(/assessRunning\s*=\s*run\?\.status.*_DONE_STATES/)
  })

  it('shows the banner only when assessment is running AND prior results exist AND not dismissed', () => {
    const s = src()
    // All three conditions must be present — a running assessment with no prior data should not
    // show a "results below are stale" banner (there are no results below).
    expect(s).toMatch(/showStaleBanner\s*=\s*assessRunning.*files\.length.*staleDismissed/)
  })

  it('resets the dismissed flag when the scan changes (runId)', () => {
    const s = src()
    // Without this reset, a user who dismissed the banner on scan A navigates away, starts scan B,
    // comes back, and sees no banner — even though scan B has a new running assessment.
    expect(s).toMatch(/setStaleDismissed\(false\).*\[runId\]|setStaleDismissed.*false.*runId/s)
  })

  it('renders the banner conditionally on showStaleBanner', () => {
    const s = src()
    expect(s).toMatch(/\{showStaleBanner &&/)
  })

  it('includes the assessedAt date in the banner message', () => {
    const s = src()
    // "results below are from [assessedAt]" is the key phrase. Without the actual date, the
    // user cannot know WHICH prior assessment the stale figures belong to.
    expect(s).toMatch(/assessedAt.*previous assessment|previous assessment.*assessedAt/s)
    // assessedAt should appear inside the stale-banner block itself, not just elsewhere on page.
    const bannerStart = s.indexOf('showStaleBanner &&')
    const bannerEnd = s.indexOf('rem-scope-disc', bannerStart)
    const bannerBlock = s.slice(bannerStart, bannerEnd)
    expect(bannerBlock).toMatch(/assessedAt/)
  })

  it('"View assessment progress" navigates to the Assess tab', () => {
    const s = src()
    // The button must call onNavigate with 'assess' — not a string like 'overview' or 'discover' —
    // so the user lands on the live scan progress, not another page.
    expect(s).toMatch(/onNavigate\?\.\('assess'\)/)
  })

  it('"Continue from previous results" dismisses the banner via staleDismissed', () => {
    const s = src()
    // setStaleDismissed(true) hides the banner for the current scan session. It is reset by the
    // runId effect above, so it does not persist across scan boundaries.
    const bannerStart = s.indexOf('showStaleBanner &&')
    const bannerEnd = s.indexOf('rem-scope-disc', bannerStart)
    const bannerBlock = s.slice(bannerStart, bannerEnd)
    expect(bannerBlock).toMatch(/setStaleDismissed\(true\)/)
  })

  it('uses role="status" so screen readers announce the new-assessment condition', () => {
    const s = src()
    const bannerStart = s.indexOf('showStaleBanner &&')
    const bannerEnd = s.indexOf('rem-scope-disc', bannerStart)
    const bannerBlock = s.slice(bannerStart, bannerEnd)
    expect(bannerBlock).toMatch(/role="status"/)
  })
})
