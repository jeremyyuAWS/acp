import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The approved board's core, actually on the screen.
//
// Ten components landed on main across #551/#558/#559/#560 and NOT ONE was mounted. That is the
// specific failure this file exists to make impossible to repeat, and it is invisible by
// construction: every one of these components self-guards and returns `null` when it has nothing
// measurable, so a component that is never mounted and a component mounted with the wrong props
// look identical on screen — blank — and the entire suite stays green either way.
//
// Source-level deliberately. Each component's BEHAVIOUR is covered by its own DOM tests
// (remediationWorkPanel, remediationApprovals, manualWork, remediationVerify, deliveryPolicy,
// closeout). What none of those can see is whether anything renders them, which is precisely what
// was wrong. This asserts the composition; they assert the components.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Comments are stripped before every negative and structural assertion. A comment naming a
// component is not a mount, and a comment explaining a removal necessarily quotes what it removed
// — testing the vocabulary instead of the claim has failed on correct code four times in this
// codebase already.
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

const PAGE_LEVEL = [
  ['RemediationWork', 'R2/R3 — the work partitioned, and the deterministic batch'],
  ['RemediationApprovals', 'R5 — the approval queue'],
  ['ManualWork', 'R6 — work ACP cannot do at all'],
  ['RemediationVerify', 'R9 — did the fixes hold'],
  ['DeliveryPanel', 'R11 — where the fixed files go'],
  ['CloseoutPanel', 'R12 — close the loop'],
]

describe('the board core is mounted, not merely shipped', () => {
  const rem = () => code('Remediate.jsx')

  for (const [name, what] of PAGE_LEVEL) {
    it(`mounts ${name} (${what})`, () => {
      const s = rem()
      expect(s, `${name} is imported`).toMatch(new RegExp(`import ${name} from '\\./${name}\\.jsx'`))
      expect(s, `${name} is RENDERED, not just imported`).toMatch(new RegExp(`<${name}[\\s/>]`))
    })
  }

  it('gives every lane-aware panel the capability tables', () => {
    // Without cap/assessment these components cannot tell `auto` from `assisted` from `human`, and
    // the lanes are the entire point of the partition. They would not crash — they would quietly
    // render a different, wrong division of the work.
    const s = rem()
    for (const name of ['RemediationWork', 'ManualWork', 'RemediationVerify']) {
      const m = s.match(new RegExp(`<${name}[^/]*?/>`, 's'))
      expect(m, `${name} mount found`).toBeTruthy()
      expect(m[0], `${name} receives cap`).toMatch(/cap=\{cap\}/)
      expect(m[0], `${name} receives assessment`).toMatch(/assessment=\{assessment\}/)
    }
  })

  it('feeds the approval queue the same items the review section reads', () => {
    // Two panels disagreeing about what is waiting for a decision is the four-denominator defect
    // in a new place. They read one queue.
    const s = rem()
    expect(s).toMatch(/<RemediationApprovals items=\{queue\}/)
  })

  it('wires approve and reject to the real handler, not a placeholder', () => {
    // `act(id, kind, …)` is the existing decision path — it posts the decision, updates the
    // counters and reloads the queue. A locally-invented handler would appear to work and record
    // nothing, which is worse than a dead button.
    const s = rem()
    expect(s).toMatch(/onApprove=\{\(id, value, meta\) => act\(id, 'approved'/)
    expect(s).toMatch(/onReject=\{\(id\) => act\(id, 'rejected'\)\}/)
  })

  it('App passes the capability tables down to Remediate', () => {
    // The chain is App → Remediate → the panels. A break anywhere in it renders every lane-aware
    // panel blank, silently.
    const s = code('App.jsx')
    const m = s.match(/<Remediate[\s\S]*?\/>/)
    expect(m).toBeTruthy()
    expect(m[0]).toMatch(/cap=\{cap\}/)
    expect(m[0]).toMatch(/assessment=\{assessment\}/)
  })
})

describe('what this commit deliberately did NOT do', () => {
  it('leaves the existing review queue in place', () => {
    // Mounting ten components and deleting the screen they replace are two changes. Doing both at
    // once makes a regression impossible to attribute, so the removal is its own commit. If this
    // case ever fails, check that the removal was intended before "fixing" it.
    const s = code('Remediate.jsx')
    expect(s).toMatch(/<RemediationInbox/)
    expect(s).toMatch(/id="rem-review"/)
  })
})

describe('the per-item four reach the detail pane, beside their subject', () => {
  // These four were the "still unmounted, and that is recorded" cases. They have now been wired,
  // so that test did its job and is replaced rather than deleted: the same four names are still
  // asserted, in the opposite direction.
  //
  // R4, R7 and R10 answer a question about ONE finding or ONE document, so a page-level mount
  // would have no subject. They are injected into RemediationInbox's detail pane through a render
  // prop, which keeps the composition with Remediate rather than making the inbox — already the
  // page's hardest state — the place every future panel lands.
  const rem = () => code('Remediate.jsx')

  for (const name of ['RemediationFixPreview', 'RemediationDocProgress', 'DocumentAudit']) {
    it(`renders ${name} for the selected finding`, () => {
      const s = rem()
      expect(s).toMatch(new RegExp(`import ${name} from '\\./${name}\\.jsx'`))
      expect(s).toMatch(new RegExp(`<${name}[\\s/>]`))
    })
  }

  it('mounts FixOutcomes (R8) at PAGE level, not per finding', () => {
    // "What did not work in this run" is a property of the run, not of whichever finding happens
    // to be selected — so it must not be inside the detail-pane render prop.
    const s = rem()
    expect(s).toMatch(/<FixOutcomes scanId=\{run\?\.id\}/)
    // Sliced between two anchors rather than matched on indentation — a reformat must not silently
    // turn this into a test that finds nothing and therefore asserts nothing.
    const from = s.indexOf('renderDetailExtra=')
    const to = s.indexOf('queue={inboxQueue}', from)
    expect(from, 'renderDetailExtra found').toBeGreaterThan(-1)
    expect(to, 'end of the detail-pane block found').toBeGreaterThan(from)
    expect(s.slice(from, to)).not.toMatch(/<FixOutcomes/)
  })

  it('guards the empty selection rather than rendering three empty frames', () => {
    expect(rem()).toMatch(/renderDetailExtra=\{\(sel\) => \(sel \?/)
  })

  it('the inbox takes the components from its parent instead of importing them', () => {
    // A render prop, so RemediationInbox gains no new imports. If it starts importing board
    // components directly, it becomes the default home for every future panel.
    const inbox = code('RemediationInbox.jsx')
    expect(inbox).toMatch(/renderDetailExtra = null/)
    expect(inbox).toMatch(/renderDetailExtra \? renderDetailExtra\(selected\) : null/)
    for (const name of ['RemediationFixPreview', 'RemediationDocProgress', 'DocumentAudit']) {
      expect(inbox, `${name} must not be imported by the inbox`).not.toMatch(
        new RegExp(`import ${name} from`))
    }
  })
})
