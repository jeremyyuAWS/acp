import { describe, it, expect } from 'vitest'
import {
  ARCHIVED, BLOCKED, ELIGIBLE_AUTO, RECOMMEND_ONLY, RECOVERY_REQUIRED, STATES, AGE_WARNING,
  policyProblem, policySummary, refusalText, runProgress, stateSpec, stateText,
  transitionMessage,
} from './archiveAutofire.js'

// The wording is the safety mechanism on these screens, so it is asserted here — directly, in the
// module that owns it — rather than through three layers of rendering in a DOM test.

describe('the five states are distinguishable without color', () => {
  it('gives every state a text mark and a full name', () => {
    for (const [state, spec] of Object.entries(STATES)) {
      expect(spec.mark, state).toBeTruthy()
      expect(spec.label.length, state).toBeGreaterThan(3)
    }
  })

  it('never gives two states the same name', () => {
    const labels = Object.values(STATES).map((s) => s.label)
    expect(new Set(labels).size).toBe(labels.length)
  })

  it('reads correctly with no styling at all', () => {
    expect(stateText(ARCHIVED)).toBe('✓ Automatically archived')
    expect(stateText(RECOMMEND_ONLY)).toBe('— Recommended for archive')
  })

  it('reports an unrecognised state as unrecognised rather than as something reassuring', () => {
    // A future backend state must not render as a friendly-sounding label by accident.
    expect(stateSpec('completed_probably').label).toBe('State not recognised')
  })
})

describe('archived and recovery-required never blur into each other', () => {
  it('says the move was verified only for archived', () => {
    expect(STATES[ARCHIVED].help).toMatch(/verified/)
  })

  it('says recovery-required is NOT known to have moved, and is not retried', () => {
    expect(STATES[RECOVERY_REQUIRED].help).toMatch(/not known whether/)
    expect(STATES[RECOVERY_REQUIRED].help).toMatch(/not retried automatically/)
    expect(STATES[RECOVERY_REQUIRED].help).not.toMatch(/\barchived\b/)
  })

  it('never claims a blocked file was moved', () => {
    expect(STATES[BLOCKED].help).toMatch(/nothing was moved/i)
  })
})

describe('nothing suggests age is the trigger', () => {
  it('states the opposite in plain words', () => {
    expect(AGE_WARNING).toMatch(/Age never triggers a move/)
    expect(AGE_WARNING).toMatch(/last modified before/)
    expect(AGE_WARNING).toMatch(/recommendation/)
  })

  it('describes the recommendation lane as a person deciding', () => {
    expect(STATES[RECOMMEND_ONLY].help).toMatch(/A person decides/)
    expect(STATES[RECOMMEND_ONLY].help).toMatch(/never moved automatically/)
  })
})

describe('progress is measured, never estimated', () => {
  it('states the four counts and derives remaining from them', () => {
    expect(runProgress({ eligible: 12, completed: 4, blocked: 1 }))
      .toBe('12 eligible · 4 completed · 1 blocked · 7 remaining')
  })

  it('never goes negative when more finished than were counted eligible', () => {
    expect(runProgress({ eligible: 1, completed: 3, blocked: 0 })).toMatch(/0 remaining/)
  })

  it('carries no percentage — eligibility is re-decided per item, so a denominator would move', () => {
    expect(runProgress({ eligible: 10, completed: 5, blocked: 0 })).not.toMatch(/%/)
  })
})

describe('the live region announces meaningful transitions and nothing else', () => {
  it('announces a state change', () => {
    expect(transitionMessage({ state: ELIGIBLE_AUTO, file: 'a.docx' },
                             { state: ARCHIVED, file: 'a.docx' }))
      .toBe('a.docx archived and verified.')
  })

  it('says nothing when a poll found the same state again', () => {
    const same = { state: ELIGIBLE_AUTO, file: 'a.docx' }
    expect(transitionMessage(same, same)).toBe('')
  })

  it('says nothing for a state it has no message for, rather than inventing one', () => {
    expect(transitionMessage(null, { state: 'something_new', file: 'a.docx' })).toBe('')
    expect(transitionMessage(null, null)).toBe('')
  })

  it('names the reason when a file is blocked', () => {
    expect(transitionMessage(null, { state: BLOCKED, file: 'a.docx', reason: 'a hold blocks it' }))
      .toBe('a.docx blocked: a hold blocks it.')
  })

  it('never says archived about a move that was not confirmed', () => {
    const message = transitionMessage(null, { state: RECOVERY_REQUIRED, file: 'a.docx' })
    expect(message).toMatch(/needs recovery/)
    expect(message).not.toMatch(/archived/)
  })
})

describe('the policy problem mirrors the server and only decides what to offer', () => {
  const ok = { enabled: true, archive_root: 'Archive', source_connections: ['sharepoint:d1'],
               rule_ids: ['r1'], required_evidence: ['metadata_link'],
               max_actions_per_run: 25, max_actions_per_day: 100 }

  it('accepts a complete policy', () => {
    expect(policyProblem(ok)).toBe('')
  })

  it('says nothing about a disabled policy, so a draft can be filled in in any order', () => {
    expect(policyProblem({ ...ok, enabled: false, archive_root: '' })).toBe('')
  })

  it('refuses an enable with no destination, no rules, no connections or no evidence', () => {
    expect(policyProblem({ ...ok, archive_root: '' })).toMatch(/nowhere to move/)
    expect(policyProblem({ ...ok, source_connections: [] })).toMatch(/source connection/)
    expect(policyProblem({ ...ok, rule_ids: [] })).toMatch(/lifecycle rule/)
    expect(policyProblem({ ...ok, required_evidence: [] })).toMatch(/supersession evidence/)
  })

  it('refuses a per-run ceiling above the per-day one', () => {
    expect(policyProblem({ ...ok, max_actions_per_run: 200, max_actions_per_day: 10 }))
      .toMatch(/cannot exceed/)
  })
})

describe('the rule editor shows every fact the decision needs', () => {
  const policy = { enabled: true, archive_root: 'Archive/Superseded', preserve_hierarchy: true,
                   required_evidence: ['metadata_link'], max_actions_per_day: 100,
                   max_actions_per_run: 25, min_replacement_age_days: 30, dry_run: true }

  it('names the evidence, the destination, the ceiling and the dry-run status', () => {
    const rows = Object.fromEntries(policySummary(policy).map((r) => [r.label, r.value]))
    expect(rows['Evidence required']).toMatch(/retentionOf/)
    expect(rows.Destination).toMatch(/Archive\/Superseded/)
    expect(rows.Destination).toMatch(/original folder structure preserved/)
    expect(rows['Daily ceiling']).toMatch(/100 files a day/)
    expect(rows['Dry run']).toMatch(/nothing is moved/)
  })

  it('says plainly when dry run is OFF, rather than leaving it implied', () => {
    const rows = Object.fromEntries(
      policySummary({ ...policy, dry_run: false }).map((r) => [r.label, r.value]))
    expect(rows['Dry run']).toMatch(/will be moved/)
  })

  it('does not present an empty evidence list as a configured one', () => {
    const rows = Object.fromEntries(
      policySummary({ ...policy, required_evidence: [] }).map((r) => [r.label, r.value]))
    expect(rows['Evidence required']).toMatch(/nothing will be archived automatically/i)
  })
})

describe('a refusal reads as a permission, not as a bug', () => {
  it('explains a 403 in terms of who may do what', () => {
    expect(refusalText(new Error('403 Forbidden'))).toMatch(/platform admin/)
    expect(refusalText(new Error('403 Forbidden'))).toMatch(/nothing was changed/)
  })

  it('passes anything else through rather than guessing', () => {
    expect(refusalText(new Error('network down'))).toBe('network down')
  })
})
