/**
 * What ACP may say about recovering a file it has dispositioned (PRD §3 "Recoverability is
 * visible", §8's undo).
 *
 * This module exists because every sentence it produces is a claim about someone's estate, and
 * three of the four ways to get one wrong are silent:
 *
 *   - asserting a retention window nobody read (the only one in this system is ACP's own
 *     "~30 days" string in api/disposition.py, and it is a claim, not a value from the Drive API);
 *   - describing a deletion on a source ACP cannot write to at all, so the deletion never happens
 *     and the recycle bin being mentioned is fiction;
 *   - offering an Undo for a move whose before-state was discarded (api/disposition.py:408 reads
 *     the file's parents and passes them straight to removeParents; nothing records them);
 *   - defaulting an unstated source to Drive, which turns "we do not know" into a confident
 *     30-day promise. The first draft of the module did exactly that, and this file's
 *     unknown-source test is what caught it.
 *
 * The discipline is deliveryPolicy.js's: an unread fact is its own state, never `false` and never
 * a plausible number.
 */
import { describe, it, expect } from 'vitest'
import { RECOVERY, recoveryFor, recoveryLine, canUndo } from './recoveryPolicy.js'
import { CAN_WRITE_BACK } from './sharepointScopes.js'

describe('the source is never guessed', () => {
  it('reports UNKNOWN when no source was supplied, rather than assuming Drive', () => {
    const r = recoveryFor({ action: 'delete' })
    expect(r.state).toBe(RECOVERY.UNKNOWN)
    expect(r.window, 'a retention window was asserted for an unstated source').toBe(null)
    expect(recoveryLine(r)).not.toMatch(/30 days/)
  })

  it('says so plainly rather than staying silent', () => {
    // Silence reads as "nothing to worry about". The reviewer has to know the answer is missing.
    expect(recoveryLine(recoveryFor({ action: 'archive' })))
      .toMatch(/source of this file was not supplied/)
  })
})

describe('Drive, the only source ACP can action', () => {
  it('says delete means trash, and names the window ACP actually claims', () => {
    const r = recoveryFor({ action: 'delete', source: 'drive' })
    expect(r.state).toBe(RECOVERY.TRASH)
    expect(recoveryLine(r)).toMatch(/Google Drive trash/)
    expect(recoveryLine(r)).toMatch(/never deleted permanently/)
    expect(recoveryLine(r)).toMatch(/Recoverable for about 30 days/)
  })

  it('does not claim ACP can restore it', () => {
    // Drive can. ACP has no untrash path at all, so pointing at Drive's trash is the true answer.
    const r = recoveryFor({ action: 'delete', source: 'drive' })
    expect(canUndo(r)).toBe(false)
    expect(recoveryLine(r)).toMatch(/ACP cannot restore it for you/)
  })

  it('admits a move cannot be reversed because the origin was never recorded', () => {
    const r = recoveryFor({ action: 'archive', source: 'drive' })
    expect(r.state).toBe(RECOVERY.NO_RECORDED_BEFORE)
    expect(canUndo(r)).toBe(false)
    expect(recoveryLine(r)).toMatch(/does not record where it came from/)
    expect(r.window, 'a move has no retention window - it is not a deletion').toBe(null)
  })

  it('admits a rename cannot be reversed either, and points at version history', () => {
    const r = recoveryFor({ action: 'rename', source: 'drive' })
    expect(r.state).toBe(RECOVERY.NO_RECORDED_BEFORE)
    expect(recoveryLine(r)).toMatch(/does not record the previous name/)
  })
})

describe('SharePoint and OneDrive, which ACP cannot write to', () => {
  it('says nothing is performed, rather than describing a recycle bin', () => {
    // The failure mode: "recoverable from the SharePoint recycle bin (93 days)" is a sentence
    // about a deletion ACP never performs, and a number this system has never read.
    for (const source of ['sharepoint', 'onedrive']) {
      const r = recoveryFor({ action: 'delete', source })
      expect(r.state).toBe(RECOVERY.UNSUPPORTED)
      expect(r.window).toBe(null)
      expect(recoveryLine(r)).not.toMatch(/recycle bin|\d+ days/i)
      expect(recoveryLine(r)).toMatch(/read-only access/)
    }
  })

  it('tracks the scope constant rather than hardcoding read-only', () => {
    // Derived, so it corrects itself if a *.ReadWrite scope is ever added - the same trick
    // CAN_WRITE_BACK itself uses. Asserted against the constant, not against today's value.
    const line = recoveryLine(recoveryFor({ action: 'delete', source: 'sharepoint' }))
    expect(line.includes('read-only access')).toBe(!CAN_WRITE_BACK)
  })
})

describe('actions and states that touch nothing', () => {
  it('says a tag moves no file, whatever the source', () => {
    for (const source of ['drive', 'sharepoint', 'local', undefined]) {
      const r = recoveryFor({ action: 'tag', source })
      expect(r.state).toBe(RECOVERY.NOT_EXECUTED)
      expect(recoveryLine(r)).toMatch(/only records metadata/)
    }
  })

  it('says a recorded-not-executed decision has nothing to recover', () => {
    // Every candidate in the review queue today (#1182). Stated before the source is even
    // considered, because it is true regardless of which source it came from.
    const r = recoveryFor({ action: 'delete', source: 'drive', executed: false })
    expect(r.state).toBe(RECOVERY.NOT_EXECUTED)
    expect(r.window, 'a 30-day window was promised for a deletion that never happens').toBe(null)
    expect(recoveryLine(r)).toMatch(/nothing to recover/)
  })

  it('treats an unstated executed flag as unknown rather than as executed', () => {
    // undefined must not mean "yes it ran" - that is the direction that over-promises.
    expect(recoveryFor({ action: 'delete', source: 'drive' }).state).toBe(RECOVERY.TRASH)
    expect(recoveryFor({ action: 'delete', source: 'drive', executed: false }).state)
      .toBe(RECOVERY.NOT_EXECUTED)
  })

  it('refuses an unrecognised source rather than inventing a story for it', () => {
    const r = recoveryFor({ action: 'delete', source: 'box' })
    expect(r.state).toBe(RECOVERY.UNSUPPORTED)
    expect(recoveryLine(r)).toMatch(/only action Google Drive files/)
  })

  it('refuses an unrecognised action too', () => {
    const r = recoveryFor({ action: 'incinerate', source: 'drive' })
    expect(r.state).toBe(RECOVERY.UNSUPPORTED)
    expect(r.window).toBe(null)
  })
})

describe('no undo is offered anywhere today', () => {
  it('canUndo is false for every case ACP can produce', () => {
    // Not asserted as a permanent truth: undoInAcp is a field, so recording the before-state
    // turns the control on by itself. This pins that nothing claims it prematurely.
    const cases = []
    for (const source of [undefined, 'drive', 'sharepoint', 'onedrive', 'local']) {
      for (const action of ['tag', 'leave', 'delete', 'archive', 'move', 'rename']) {
        for (const executed of [undefined, false]) {
          cases.push(recoveryFor({ action, source, executed }))
        }
      }
    }
    expect(cases.length).toBe(60)
    expect(cases.filter(canUndo)).toEqual([])
  })

  it('never names a window except the one Drive trash claim', () => {
    const windows = new Set()
    for (const source of [undefined, 'drive', 'sharepoint', 'onedrive', 'local']) {
      for (const action of ['tag', 'leave', 'delete', 'archive', 'move', 'rename']) {
        const w = recoveryFor({ action, source }).window
        if (w) windows.add(w)
      }
    }
    expect([...windows]).toEqual(['about 30 days'])
  })
})

describe('recoveryLine', () => {
  it('appends the window only when one is known', () => {
    expect(recoveryLine(recoveryFor({ action: 'delete', source: 'drive' }))).toMatch(/Recoverable for/)
    expect(recoveryLine(recoveryFor({ action: 'archive', source: 'drive' }))).not.toMatch(/Recoverable for/)
  })

  it('is empty for nothing, rather than throwing into a render', () => {
    expect(recoveryLine(null)).toBe('')
    expect(recoveryLine(undefined)).toBe('')
  })
})
