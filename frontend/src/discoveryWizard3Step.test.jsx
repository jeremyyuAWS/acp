import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { gotoStep, backToStart, forwardBtn, backBtn, currentStepTitle } from './wizardNav.testkit.js'
import { WIZARD_STEPS, FIRST_STEP, LAST_STEP, stepInfo, stepBlockedReason,
         nextStep, prevStep, forwardLabel, railState } from './discoveryWizardSteps.js'

// "New discovery", as three steps — the approved boards.
//
// Source and folders → Lifecycle rules → Review and run. The content all existed; what did not was
// the flow, and the lifecycle rules were reachable only AFTER a run, which is one run too late:
// those rules tag files DURING discovery, so a user who first meets them on the results screen has
// already produced an inventory the rules never touched.
//
// The rail came back for the reason the note that removed it gave. It argued a progress rail over
// ONE step is chrome; that was true when #532 left a single decision here. There are three real
// ones now, and the rail tracks that number.

afterEach(unmountAll)

const listDispositionPolicies = vi.fn(async () => [])
vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: {} })),
  setScanLocations: vi.fn(async () => ({ ok: true })),
  listFolders: vi.fn(async () => ({ folders: [{ id: 'hr', name: 'HR' }] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
  listDispositionPolicies: (...a) => listDispositionPolicies(...a),
  createDispositionPolicy: vi.fn(async () => ({ ok: true })),
  setDispositionPolicyEnabled: vi.fn(async () => ({ ok: true })),
  previewDispositionPolicy: vi.fn(async () => ({ would_match: 0 })),
}))

const { default: ScanScopeWizard } = await import('./ScanScopeWizard.jsx')

const mount = async (props = {}) => {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ScanScopeWizard, {
      showStartButton: true, source: 'drive', hasDrive: true, hasSP: false,
      onStartScan: () => {}, scans: [], ...props,
    }))
  })
  return container
}

describe('the step model', () => {
  it('is the three the boards name, in order', () => {
    expect(WIZARD_STEPS.map((s) => s.title))
      .toEqual(['Source and folders', 'Lifecycle rules', 'Review and run'])
    expect(FIRST_STEP).toBe(1)
    expect(LAST_STEP).toBe(3)
  })

  it('labels the forward control per step, as the boards do', () => {
    expect(forwardLabel(1)).toBe('Continue to rules →')
    expect(forwardLabel(2)).toBe('Continue to review →')
    // Not "Continue": the last control starts a run against somebody's estate and should name the
    // action rather than the navigation.
    expect(forwardLabel(3)).toBe('Run discovery →')
    // A step number that is not ours renders a real string, never `undefined` inside a button.
    expect(forwardLabel(99)).toBe('Continue →')
  })

  it('walks forward and back, and stops at both ends', () => {
    expect(nextStep(1, 'all', [])).toBe(2)
    expect(nextStep(3, 'all', [])).toBe(null)
    expect(prevStep(1)).toBe(null)
    expect(prevStep(3)).toBe(2)
  })

  it('blocks ONLY step 1, and only for the empty-narrowing reason', () => {
    // An empty folder list under "Specific folders" falls through to the WHOLE source, so
    // advancing from it authorises the opposite of what the mode says (#502).
    expect(stepBlockedReason(1, 'some', [])).toMatch(/at least one folder/i)
    expect(nextStep(1, 'some', [])).toBe(null)
    // Not narrowing: empty is the honest answer there.
    expect(stepBlockedReason(1, 'all', [])).toBe(null)
    // Later steps never block. A discovery with no lifecycle rules is a perfectly good discovery,
    // and requiring one would invent a prerequisite the backend does not have.
    expect(stepBlockedReason(2, 'some', [])).toBe(null)
    expect(stepBlockedReason(3, 'some', [])).toBe(null)
  })

  it('marks the rail behind you done, never ahead', () => {
    const r = railState(2)
    expect(r.map((s) => s.done)).toEqual([true, false, false])
    expect(r.map((s) => s.current)).toEqual([false, true, false])
    expect(r.map((s) => s.upcoming)).toEqual([false, false, true])
  })

  it('has a subtitle for the two steps the boards give one', () => {
    expect(stepInfo(1).subtitle).toMatch(/Choose where ACP should inventory/)
    expect(stepInfo(2).subtitle).toMatch(/tag matching files/i)
    // The review's heading carries its own framing; a subtitle there would be a third voice.
    expect(stepInfo(3).subtitle).toBe(null)
  })
})

describe('the wizard, walked', () => {
  it('opens on step 1 with the folder question and no review', async () => {
    const c = await mount()
    expect(currentStepTitle(c)).toBe('Source and folders')
    expect(c.textContent).toMatch(/Every accessible folder/)
    expect(c.textContent).toMatch(/Specific folders/)
    // The review's content must NOT be on this screen — that was the whole defect of one page.
    expect(c.textContent).not.toMatch(/READY TO DISCOVER/i)
    expect(c.textContent).not.toMatch(/WHAT HAPPENS NEXT/i)
    expect(forwardBtn(c).textContent).toMatch(/Continue to rules/)
    // Step 1 offers Cancel, not Back.
    expect(backBtn(c)).toBe(null)
  })

  it('reaches the rules editor on step 2', async () => {
    const c = await mount()
    await gotoStep(c, act, 2)
    expect(currentStepTitle(c)).toBe('Lifecycle rules')
    expect(c.textContent).toMatch(/Rules run during discovery/i)
    // The SAME component the Discover tab mounts, identified by copy only it carries — the
    // archive-beats-delete conflict rule, which is the safety claim a second implementation
    // would drift on first.
    expect(c.textContent).toMatch(/keeps the/i)
    expect(forwardBtn(c).textContent).toMatch(/Continue to review/)
    expect(backBtn(c)).toBeTruthy()
  })

  it('reaches the review on step 3, with the promise and the sequence', async () => {
    const c = await mount()
    await gotoStep(c, act, 3)
    expect(currentStepTitle(c)).toBe('Review and run')
    expect(c.textContent).toMatch(/no file is opened/i)
    expect(c.textContent).toMatch(/READY TO DISCOVER/)
    expect(c.textContent).toMatch(/WHAT HAPPENS NEXT/)
    expect(c.textContent).toMatch(/Every file in scope is listed from its metadata/)
    expect(forwardBtn(c).textContent).toMatch(/Run discovery/)
  })

  it('never says a file was archived or deleted, on any step', async () => {
    // The one screen where somebody authorises a rule that SOUNDS destructive and is not. The rule
    // engine writes a lifecycle_status and one audit row; nothing is moved, trashed or renamed.
    //
    // A CLAIM ABOUT FILES, not a banned word: this copy names the actions in order to deny them
    // ("Nothing is moved, trashed or changed", "tagged for archive review"), so a whole-word ban
    // would match its own denial — testing the vocabulary instead of the claim.
    const claim = /\bfiles?\s+(is|are|was|were|will be|have been|has been)\s+\w*\s*(archived|deleted|trashed|removed|moved)\b/i
    const c = await mount()
    for (const step of [1, 2, 3]) {
      // eslint-disable-next-line no-await-in-loop
      await gotoStep(c, act, step)
      expect(c.textContent, `step ${step} claims a file was acted on`).not.toMatch(claim)
    }
  })

  it('goes back without losing the scope', async () => {
    // Back is never disabled — a user who cannot retreat from a step they cannot complete is stuck
    // inside a modal, which is worse than any scope mistake this wizard guards against.
    const c = await mount()
    await gotoStep(c, act, 3)
    await backToStart(c, act)
    expect(currentStepTitle(c)).toBe('Source and folders')
    expect(c.textContent).toMatch(/Every accessible folder/)
  })

  it('re-reads the rules on arrival at the review, not once at mount', async () => {
    // Step 2 is an EDITOR. A list loaded once would let the review summarise the rule set as it
    // was BEFORE the user edited it — and that summary is what the run is authorised against
    // (DS-07). Stale by exactly one screen is worse than absent: specific, plausible and wrong.
    listDispositionPolicies.mockClear()
    const c = await mount()
    // Not on step 1: the endpoint is admin-only, so a non-admin gets a guaranteed 403 for an
    // answer this screen does not show.
    expect(listDispositionPolicies).not.toHaveBeenCalled()

    // DELTAS, not absolutes. Step 2 mounts DispositionRules, which loads the same list for its own
    // editor — so the total after step 3 counts both reads, and an exact number here would pin an
    // implementation detail of a different component. What this case is about is whether the
    // REVIEW re-reads: arriving at step 3 must add a call each time.
    await gotoStep(c, act, 2)
    const afterRules = listDispositionPolicies.mock.calls.length
    await gotoStep(c, act, 3)
    const afterReview = listDispositionPolicies.mock.calls.length
    expect(afterReview, 'the review did not read the rules on arrival').toBeGreaterThan(afterRules)

    await backToStart(c, act)
    await gotoStep(c, act, 3)
    expect(listDispositionPolicies.mock.calls.length,
      'the review reused a rule list from before step 2').toBeGreaterThan(afterReview)
  })
})

describe('embedded without the run footer, nothing changed', () => {
  it('shows every region at once, because there is no way to navigate', async () => {
    // ScanReviewModal is the only caller that passes showStartButton. Mounted as a panel there is
    // no footer to walk with, so gating regions behind a step nobody can change would hide them
    // permanently — a stepper that silently deletes content is worse than no stepper.
    const c = await mount({ showStartButton: false })
    expect(c.querySelector('[aria-current="step"]'), 'a rail appeared with no way to use it').toBe(null)
    expect(forwardBtn(c)).toBe(null)
    expect(c.textContent).toMatch(/Choose where ACP should inventory/)
  })
})
