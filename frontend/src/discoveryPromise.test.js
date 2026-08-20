/**
 * Two sentences the review step says before a discovery run, and what they are forbidden to say.
 *
 * `lifecycleRuleSummary` has exactly one interesting property and it is not the arithmetic: the
 * difference between "we asked and the answer is none" and "we have not asked". Both render as an
 * absence of tags afterwards, and only one of them is a promise. Collapsing them to `{count: 0}`
 * would put "No file will be tagged for archive or deletion review." on screen on the strength of
 * a failed HTTP call — the #517 `by_age` mistake, made about a destructive-sounding action.
 *
 * The wording cases below are not style policing. The PRD's rule is that ACP never says a file was
 * archived or deleted when it has written a recommendation, and the summary line is the first
 * place in the product where a count of DELETE rules appears next to a verb.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { METADATA_ONLY_TITLE, METADATA_ONLY_BODY, lifecycleRuleSummary } from './discoveryPromise.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

const rule = (over) => ({ policy_id: 'p1', name: 'Stale HR', action: 'archive', enabled: 1, ...over })

describe('an unknown rule set is not an empty one', () => {
  it('returns null before the rules have loaded', () => {
    // The caller renders nothing on null. Anything else here is a claim about files.
    expect(lifecycleRuleSummary(null)).toBeNull()
    expect(lifecycleRuleSummary(undefined)).toBeNull()
  })

  it('returns null for a non-list, which is what a failed read hands back', () => {
    // `j()` on an error body yields an object, not an array — the shape a 403 arrives as.
    expect(lifecycleRuleSummary({ detail: 'forbidden' })).toBeNull()
    expect(lifecycleRuleSummary('')).toBeNull()
  })

  it('distinguishes that from a measured zero', () => {
    const s = lifecycleRuleSummary([])
    expect(s, 'an empty rule list rendered as "unknown"').not.toBeNull()
    expect(s.count).toBe(0)
    expect(s.line).toMatch(/none/i)
  })
})

describe('what counts as a rule that will run', () => {
  it('counts only enabled rules', () => {
    // Rules are created DISABLED and stay that way until somebody enables them; a disabled rule
    // tags nothing, so counting it would overstate what this run does.
    expect(lifecycleRuleSummary([rule({ enabled: 0 }), rule({ policy_id: 'p2' })]).count).toBe(1)
  })

  it('accepts the 0/1 the API actually returns, not just booleans', () => {
    // `enabled` comes back as an integer from SQLite. A `=== true` test would count nothing, and
    // the screen would read "None enabled" on a workspace with rules running.
    expect(lifecycleRuleSummary([rule({ enabled: 1 })]).count).toBe(1)
    expect(lifecycleRuleSummary([rule({ enabled: true })]).count).toBe(1)
  })

  it('counts only the two lifecycle actions', () => {
    // The policy table is shared; a non-lifecycle policy tags no file for archive or deletion, so
    // counting it here would attribute a disposition to a run that made none.
    const s = lifecycleRuleSummary([
      rule({ action: 'archive' }), rule({ policy_id: 'p2', action: 'delete' }),
      rule({ policy_id: 'p3', action: 'notify' }), rule({ policy_id: 'p4', action: undefined }),
    ])
    expect(s.count).toBe(2)
  })

  it('survives a malformed row rather than throwing on the review step', () => {
    expect(lifecycleRuleSummary([null, undefined, rule()]).count).toBe(1)
  })

  it('names the rules, skipping the unnamed', () => {
    const s = lifecycleRuleSummary([rule({ name: 'Stale HR' }), rule({ policy_id: 'p2', name: '' })])
    expect(s.names).toEqual(['Stale HR'])
  })
})

describe('what the sentences claim', () => {
  it('says a rule TAGS, never that it archived or deleted', () => {
    // "2 enabled" alone does not distinguish tagging from acting, and the reader most likely to
    // misread it is the one authorising a run over a drive they own.
    //
    // Asserted as a CLAIM ABOUT FILES, not as banned vocabulary. The first draft of this forbade
    // the words outright and failed on the sentence it was written to protect — "Nothing is moved,
    // trashed or changed", which says the right thing BY naming the actions and denying them.
    // Banning the word would have forced the copy to get vaguer to satisfy a test. What the PRD
    // forbids is the product saying a file was acted on when it wrote a recommendation, so the
    // pattern below needs a file as the subject.
    const s = lifecycleRuleSummary([rule({ action: 'delete' })])
    expect(s.detail).toMatch(/tagged for review/i)
    expect(s.detail, 'the detail line claims files were archived, deleted or moved')
      .not.toMatch(/\bfiles?\s+(is|are|was|were|will be|have been|has been)\s+\w*\s*(archived|deleted|trashed|removed|moved)\b/i)
    expect(lifecycleRuleSummary([]).detail).toMatch(/No file will be tagged/i)
  })

  it('states the metadata-only promise in terms of what is NOT read', () => {
    // The claim is falsifiable and load-bearing: no download, no content inspection, no change at
    // the source. A title that only said "metadata" would be true and unhelpful.
    expect(METADATA_ONLY_TITLE).toMatch(/no file is opened/i)
    expect(METADATA_ONLY_BODY).toMatch(/does not download/i)
    expect(METADATA_ONLY_BODY).toMatch(/does not modify/i)
  })

  it('does not promise that content is never read at all', () => {
    // It is read later, at Assess, for the files chosen there. A flat "ACP never reads your
    // documents" would be the comfortable sentence and a false one.
    expect(METADATA_ONLY_BODY).toMatch(/assess/i)
  })
})

describe('the wizard actually says it', () => {
  // A module nobody imports promises nothing. These are source assertions because the DOM cases
  // in wizardDiscoveryPromise.test.jsx cover the render — this pins the wiring itself.
  const src = () => read('ScanScopeWizard.jsx')

  it('renders both halves on the review step', () => {
    expect(src()).toMatch(/METADATA_ONLY_TITLE/)
    expect(src()).toMatch(/METADATA_ONLY_BODY/)
    expect(src()).toMatch(/lifecycleRuleSummary\(policies\)/)
  })

  it('holds the rules in state that starts unknown', () => {
    // `useState(null)` and no `catch` that sets `[]`: a failed load must stay null.
    expect(src()).toMatch(/const \[policies, setPolicies\] = useState\(null\)/)
    expect(src(), 'a failed policy read falls back to an empty list')
      .not.toMatch(/catch\(\(\) => setPolicies\(\[\]\)\)/)
  })
})

describe('the scope screen sets a discovery boundary, not an assessment one', () => {
  // The wizard chooses WHERE ACP inventories. What gets scored against WCAG is chosen later, in
  // Assess, against the inventory this produces. Copy here that says "assess" invites a folder
  // choice to be read as a decision about scoring — the conflation the Discover/Assess split
  // removed, left behind by #532 when it stripped the format and criterion pickers out.
  //
  // Found by diffing the shipped screen against the approved design board rather than by a test
  // failing: nothing was broken, the screen simply described itself as the wrong stage.
  const src = () => read('ScanScopeWizard.jsx')

  it('offers to INVENTORY the selected folders, not to assess them', () => {
    expect(src()).toMatch(/'Inventory only selected projects or departments'/)
    expect(src(), 'the scope choice still describes itself as assessment')
      .not.toMatch(/'Assess only selected/)
  })

  it('still says what selecting a folder actually covers', () => {
    // The recursion promise is the other half of the boundary and has to survive the rewording.
    expect(read('FolderPicker.jsx')).toMatch(/all subfolders, recursively/)
  })
})
