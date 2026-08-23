import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Source-level wiring for the Release Center's Phase 2 surface (honest policy panel + confirmation
// modal + per-row destination). A full mount would need the whole run/files fixture stack; the
// honesty-critical copy is unit-tested in releasePolicy.test.js — this pins that Publish.jsx uses it.
const HERE = dirname(fileURLToPath(import.meta.url))
const pub = () => readFileSync(join(HERE, 'Publish.jsx'), 'utf8')

describe('Release Center: honest policy panel', () => {
  it('reads the REAL policy from settings rather than hard-coding it', () => {
    const s = pub()
    expect(s).toMatch(/import \{ releaseDestination, releaseDestinationPhrase, releaseConfirmLines \} from '\.\/releasePolicy\.js'/)
    expect(s).toMatch(/getSettings\(\)\.then\(/)
    expect(s).toMatch(/mirrorState\(settings\)/)
    expect(s).toMatch(/driveMirrorEnabled = ms === MIRROR\.ON/)
  })

  it('shows a policy panel with the destination and the “why not in place” explainer', () => {
    const s = pub()
    expect(s).toMatch(/Release policy/)
    expect(s).toMatch(/releaseDestinationPhrase\(\{ anyDrive, driveMirrorEnabled, driveMirrorFolder \}\)/)
    expect(s).toMatch(/Why can’t I replace the original\?/)
    expect(s).toMatch(/never overwritten/)
  })

  it('keeps the conformance disclaimer and no un-backed “preserved” claim (Phase 1 guardrail holds)', () => {
    const s = pub()
    // The header still disclaims certification in the rendered copy…
    expect(s).toMatch(/it does not certify overall conformance/)
    // …and the retracted "Original preserved" wording never comes back (it appears in no comment
    // here either, so a plain absence check is safe — unlike "certifiable", which the Phase 1
    // explainer comments legitimately still quote).
    expect(s).not.toMatch(/Original preserved/)
    expect(s).not.toMatch(/\bis certified\b/)
  })
})

describe('Release Center: confirmation before a release', () => {
  it('routes both Release and Release-all through a confirm step, not a direct write', () => {
    const s = pub()
    expect(s).toMatch(/onClick=\{\(\) => setConfirm\(\{ kind: 'all' \}\)\}/)
    expect(s).toMatch(/onClick=\{\(\) => setConfirm\(\{ kind: 'file', file: f\.file \}\)\}/)
    // The old direct-fire handlers are gone.
    expect(s).not.toMatch(/onClick=\{publishAll\}/)
    expect(s).not.toMatch(/onClick=\{\(\) => publish\(f\.file\)\}/)
  })

  it('the modal states the checkable consequences and only then calls the real publish path', () => {
    const s = pub()
    expect(s).toMatch(/role="dialog" aria-modal="true"/)
    expect(s).toMatch(/releaseConfirmLines\(\{ count: cnt, anyDrive: batchAnyDrive/)
    expect(s).toMatch(/setConfirm\(null\); if \(isAll\) publishAll\(\); else publish\(confirm\.file\)/)
    // Escape closes it.
    expect(s).toMatch(/if \(e\.key === 'Escape'\) setConfirm\(null\)/)
  })

  it('labels each row with where its corrected copy will land', () => {
    const s = pub()
    expect(s).toMatch(/releaseDestination\(\{ driveFileId: f\.drive_file_id, driveMirrorEnabled, driveMirrorFolder \}\)\.label/)
  })
})
