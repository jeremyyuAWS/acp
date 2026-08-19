import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Remediate stacked eight always-open panels. An operator working the queue reads ONE of them;
// the rest are reference they scroll past on every visit, which is most of why this screen reads
// as busy. These pin the structure that fixed it.
//
// Source-level, same reasoning as v2Simplification.test.js and scopeStep.test.js: this asserts
// which sections collapse and what their default open state is DERIVED from. A mount-based test
// would need the whole run/files/decisions fixture stack, and one that silently rendered an empty
// Remediate would pass every "this section is collapsible" assertion by rendering nothing at all.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('v2 Remediate: collapsible sections', () => {
  const rem = () => read('Remediate.jsx')

  it('has a RemSection helper built on <details>', () => {
    const s = rem()
    expect(s).toMatch(/function RemSection\(/)
    // <details> and not a button+useState: it is natively keyboard-operable and announces its
    // own expanded state, so there is no aria-expanded to drift out of sync — which is exactly
    // the kind of rot that embarrasses a product certifying accessibility.
    expect(s).toMatch(/<details className="panel rem-sec"/)
    expect(s).not.toMatch(/aria-expanded=\{.*remSec/i)
  })

  it('collapses the four reference sections', () => {
    const s = rem()
    for (const id of ['rem-verify', 'rem-docs', 'rem-self', 'rem-deferred']) {
      expect(s, `${id} should be a RemSection`).toMatch(
        new RegExp(`<RemSection[^>]*id="${id}"`))
    }
  })

  it('leaves the Review queue open — it is the work, not reference', () => {
    // The one section an operator actually acts in. Collapsing it would put a click between them
    // and the only task on the page.
    const s = rem()
    expect(s).toMatch(/<section className="panel rem-review-panel" id="rem-review">/)
    expect(s).not.toMatch(/<RemSection[^>]*id="rem-review"/)
  })

  it('keeps the count visible when a section is collapsed', () => {
    // A collapsed "Deferred" that does not say how many is worse than no control at all: the
    // number is the whole basis for deciding whether to open it.
    const s = rem()
    expect(s).toMatch(/<RemSection[^>]*id="rem-deferred"[\s\S]{0,200}?count=\{deferredItems\.length\}/)
    expect(s).toMatch(/<RemSection[^>]*id="rem-docs"[\s\S]{0,200}?count=\{docList\.length\}/)
    // …and RemSection must actually render it, not just accept the prop.
    expect(s).toMatch(/count != null && <span className="reviewpill">\{count\}<\/span>/)
  })

  it('derives defaultOpen from content rather than hard-coding it', () => {
    const s = rem()
    // Documents opens only when there are documents; Verification only when something is
    // running or verified. A constant would either nag forever or hide the section exactly
    // when it matters.
    expect(s).toMatch(/id="rem-docs"[\s\S]{0,200}?defaultOpen=\{docList\.length > 0\}/)
    expect(s).toMatch(/id="rem-verify"[\s\S]{0,400}?defaultOpen=\{verifyState === 'running' \|\| revalidated\.length > 0\}/)
  })

  it('leaves Deferred closed even though it has items', () => {
    // Deferred means "decided, revisit later". Opening it every visit re-litigates a decision
    // the operator already made — the opposite of what deferring was for.
    const s = rem()
    const block = s.match(/<RemSection[^>]*id="rem-deferred"[^>]*>/)[0]
    expect(block).not.toMatch(/defaultOpen/)
  })
})

describe('v2: the simplification left no dangling pointers', () => {
  // #151 deleted the Permissions and Business ontology tabs but not the prose telling operators
  // to open them. The worst was an EMPTY STATE whose entire job is to say what to do next, and
  // what it said was "open a screen that is not there".
  //
  // UserManagement.jsx was one of the files swept here; it has since been deleted outright — it
  // was a hardcoded roster standing in for the list of users with access — so it is no longer a
  // file that can point anywhere. `Settings → Test users` joins the dead list in its place: that
  // tab was merged into `Settings → Users`, and a renamed tab strands prose exactly as a removed
  // one does.
  it('never sends an operator to a Settings tab v2 removed or renamed', () => {
    for (const f of ['Remediate.jsx', 'Settings.jsx', 'IntegrationRoadmap.jsx']) {
      const s = read(f)
      for (const dead of ['Settings → Permissions', 'Settings → Business ontology',
                          'Settings → Validation coverage', 'Settings → Test users']) {
        expect(s, `${f} still points at "${dead}"`).not.toContain(dead)
      }
    }
  })
})
