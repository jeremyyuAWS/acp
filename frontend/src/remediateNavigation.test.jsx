import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Redesign spec R4 item 1 — "drop the ProgressRail as a persistent element".
//
// The spec's complaint was FOUR competing navigation systems on the Remediate page: the primary
// tabs, scan metadata / time travel, the Scan→Assess→Remediate→…→Publish rail, and the per-finding
// Detected→…→Certified rail. Keep the primary tabs; collapse the rest into contextual status
// inside the page. The rail was the last of the redundant ones still rendering.
//
// THE HALF THAT ACTUALLY NEEDS GUARDING IS NOT THE DELETION. Asserting that something is absent is
// cheap and nearly worthless on its own — it passes just as happily if the whole page is gone. The
// claim this change makes is narrower and falsifiable: every state the rail showed is still on the
// page, said closer to the work. So each case below pairs "the rail is gone" with "its replacement
// is still here", because deleting a duplicate is only correct while the original survives.
//
// Source-level, matching remediateCollapse.test.js: Remediate mounts a page's worth of
// dependencies, and what is asserted here is where things sit in the tree, not behaviour. The
// components' own behaviour is covered by scanScope/workflowStatus/RemediationInbox tests.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('the Remediate page has one navigation system, not two', () => {
  it('no longer renders the progress rail', () => {
    const r = read('Remediate.jsx')
    expect(r).not.toMatch(/<ProgressRail/)
    expect(r).not.toMatch(/function ProgressRail/)
    expect(r).not.toMatch(/const progressSteps\s*=/)
    // The stylesheet too. Orphaned CSS for a deleted component is how a "removed" element comes
    // back: the next person to write markup finds .progressrail styled and assumes it is live.
    expect(read('styles.css')).not.toMatch(/\.progressrail|\.prstep|\.prmark|\.prcount|\.prsep/)
  })

  it('still says where Remediate itself stands — in the hero, not a rail step', () => {
    const r = read('Remediate.jsx')
    expect(r).toMatch(/<div className="rem-hero-line">/)
    expect(r).toMatch(/document\{files\.length === 1 \? '' : 's'\} processed/)
  })

  it('still says how much review is left — once, in the section that holds the work', () => {
    // This is the count #272/#273 deduplicated down to one dominant statement. The rail carried a
    // fourth copy of it; what must survive is the sentence and the progress track beside it.
    const r = read('Remediate.jsx')
    expect(r).toMatch(/need review across/)
    expect(r).toMatch(/<div className="conftrack"/)
  })

  it('still says where verification stands — with more detail than the rail had', () => {
    // <VerifyState> carries state, percentage, remaining and ready. The rail step carried one of
    // 'done' | 'active' | 'pending'. Removing the rail loses nothing here; it drops a summary of
    // a richer thing rendered twenty lines further down.
    const r = read('Remediate.jsx')
    expect(r).toMatch(/<RemSection id="rem-verify" title="Verification"/)
    expect(r).toMatch(/<VerifyState state=\{verifyState\}/)
  })

  it('still offers Publish as the next step — as the primary action', () => {
    expect(read('Remediate.jsx')).toMatch(/label: 'Publish Certified Copy →'/)
  })

  it('keeps the contextual workflow status the spec asked for in the rail’s place', () => {
    // The reason this deletion is safe NOW and would not have been when the spec was written:
    // #366 put a workflow tablist inside the inbox and #370 lit each finding's live step in the
    // footer. Remove those and the rail's removal becomes a real loss of wayfinding, so the page
    // must keep mounting the inbox that carries them.
    expect(read('Remediate.jsx')).toMatch(/<RemediationInbox/)
    const inbox = read('RemediationInbox.jsx')
    expect(inbox).toMatch(/WORKFLOW_TABS/)
    expect(inbox).toMatch(/role="tablist"/)
  })
})
