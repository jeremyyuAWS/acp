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
    expect(s).toMatch(/releaseDestinationPhrase\(\{ provider: releaseProvider, anyDrive, driveMirrorEnabled, driveMirrorFolder \}\)/)
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
  it('routes the selected batch through a confirm step, not a direct write', () => {
    const s = pub()
    expect(s).toMatch(/onClick=\{\(\) => setConfirm\(\{ kind: 'selected', files: selectedReady\.map/)
    // The old direct-fire handlers are gone.
    expect(s).not.toMatch(/onClick=\{publishAll\}/)
    expect(s).not.toMatch(/onClick=\{\(\) => publish\(f\.file\)\}/)
  })

  it('the modal states the checkable consequences and only then calls the real publish path', () => {
    const s = pub()
    expect(s).toMatch(/role="dialog" aria-modal="true"/)
    expect(s).toMatch(/releaseConfirmLines\(\{ count: cnt, provider: releaseProvider, anyDrive: batchAnyDrive/)
    expect(s).toMatch(/setConfirm\(null\); if \(isBatch\) publishAll\(targets\.map\(\(f\) => f\.file\)\); else publish\(confirm\.file\)/)
    // Escape closes it.
    expect(s).toMatch(/if \(e\.key === 'Escape'\) setConfirm\(null\)/)
  })

  it('labels each row with where its corrected copy will land', () => {
    const s = pub()
    expect(s).toMatch(/releaseDestination\(\{ provider: releaseProvider, driveFileId: f\.drive_file_id, driveMirrorEnabled, driveMirrorFolder \}\)\.label/)
  })

  it('shows one release destination and an accessible two-column document view', () => {
    const s = pub()
    expect(s).toMatch(/aria-label="Release destination"/)
    expect(s).toMatch(/Open release folder/)
    expect(s).toMatch(/Original files are unchanged/)
    expect(s).toMatch(/Documents grouped by source folder/)
    expect(s).toMatch(/Selected document release details/)
    expect(s).toMatch(/aria-live="polite"/)
    expect(s).toMatch(/<details[^>]*><summary>Audit history/)
  })

  it('follows durable SharePoint jobs instead of treating submission as completion', () => {
    const s = pub()
    expect(s).toMatch(/releaseProvider === 'sharepoint' && res\?\.queued/)
    expect(s).toMatch(/await getReleaseStatus\(run\.id\)/)
    expect(s).toMatch(/row\.status === 'queued' \|\| row\.status === 'running'/)
    expect(s).toMatch(/still running safely in the background/)
  })
})

describe('Release builder', () => {
  it('starts with an eligible-file selection and offers real publish and download paths', () => {
    const s = pub()
    expect(s).toMatch(/Start a release/)
    expect(s).toMatch(/Choose files/)
    expect(s).toMatch(/Choose delivery/)
    expect(s).toMatch(/Publish copies/)
    expect(s).toMatch(/Download corrected files/)
    expect(s).toMatch(/downloadRemediated\(run\?\.id, file\.file\)/)
  })

  it('publishes only the selected files and states the consequence before writing', () => {
    const s = pub()
    expect(s).toMatch(/setConfirm\(\{ kind: 'selected', files: selectedReady\.map/)
    expect(s).toMatch(/publishAll\(targets\.map/)
    expect(s).toMatch(/Original files will not be changed/)
    expect(s).toMatch(/Publish \$\{selectedReady\.length\}/)
  })

  it('does not allow changed sources into the releasable selection', () => {
    const s = pub()
    expect(s).toMatch(/srcOf\(f\) !== 'stale'/)
    expect(s).toMatch(/disabled=\{done\[f\.file\] \|\| srcOf\(f\) === 'stale'\}/)
  })

  it('moves focus from the overview action to the real builder', () => {
    const s = pub()
    expect(s).toMatch(/const builderRef = useRef\(null\)/)
    expect(s).toMatch(/onClick=\{startRelease\}>Start a release/)
    expect(s).toMatch(/builderRef\.current\?\.scrollIntoView/)
    expect(s).toMatch(/builderRef\.current\?\.focus/)
    expect(s).toMatch(/ref=\{builderRef\} tabIndex=\{-1\} aria-labelledby="release-workspace-title"/)
  })

  it('collapses the secondary record so it no longer buries the workflow', () => {
    const s = pub()
    expect(s).toMatch(/<details className="panel release-record"/)
    expect(s).toMatch(/Release details and evidence/)
    expect(s).toMatch(/<summary className="release-record__summary">/)
  })

  it('uses three distinct steps instead of combining delivery and review', () => {
    const s = pub()
    expect(s).toMatch(/const \[builderStep, setBuilderStep\] = useState\(1\)/)
    expect(s).toMatch(/builderStep === 1 \? \(/)
    expect(s).toMatch(/builderStep === 2 \? <>/)
    expect(s).toMatch(/setBuilderStep\(2\)\}>Choose delivery/)
    expect(s).toMatch(/setBuilderStep\(3\)\}>Review release/)
    expect(s).toMatch(/setBuilderStep\(1\)\}>Back to files/)
    expect(s).toMatch(/setBuilderStep\(2\)\}>Back to delivery/)
  })

  it('announces the active step to assistive technology', () => {
    const s = pub()
    expect(s.match(/aria-current=\{builderStep === [123] \? 'step' : undefined\}/g)).toHaveLength(3)
  })

  it('turns a partial release into a reviewable retry plan for only failed files', () => {
    const s = pub()
    expect(s).toMatch(/releaseResults\[f\.file\]\?\.status === 'failed'/)
    expect(s).toMatch(/setSelectedFiles\(new Set\(failedReady\.map/)
    expect(s).toMatch(/setDeliveryMethod\('publish'\)/)
    expect(s).toMatch(/setBuilderStep\(3\)/)
    expect(s).toMatch(/Successful files remain published/)
    expect(s).toMatch(/completed work is not duplicated/)
    expect(s).toMatch(/Review and retry failed/)
  })

  it('keeps stale failed files out of retry and explains the rescan dependency', () => {
    const s = pub()
    expect(s).toMatch(/releaseResults\[f\.file\]\?\.status === 'failed' && srcOf\(f\) !== 'stale'/)
    expect(s).toMatch(/no longer retryable until the changed source is rescanned/)
  })
})
