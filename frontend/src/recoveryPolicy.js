// What can honestly be said about recovering a file ACP has dispositioned (PRD §8, §3's
// "Recoverability is visible": "'Delete' means move to source trash, with recovery details and
// expiry").
//
// Modelled on deliveryPolicy.js, and for the same reason: the interesting states here are not
// booleans, and a module that returns `false` for "we do not know" will eventually put that
// sentence on a screen. Its third rule is the one that matters most here — "when the setting has
// not been read, say nothing about it" — so an unknown retention window is UNKNOWN, never a
// number somebody guessed.
//
// EVERY FACT BELOW WAS CONFIRMED IN THE CODEBASE, not assumed:
//
//   frontend/src/sharepointScopes.js   SP_SCOPES holds no *.ReadWrite scope, so CAN_WRITE_BACK
//                                      is false and ACP never writes to SharePoint or OneDrive.
//   api/disposition.py  _drive_file_id  archive / move / rename / delete require a `drive:` doc
//                                      id; anything else returns "unsupported source". `tag` and
//                                      `leave` are metadata-only and work for any source.
//   api/disposition.py  execute_action  delete is `trashed: True` — Drive trash, never
//                                      permanent — and the code states ~30 days itself.
//   api/disposition.py:408             a move reads the file's parents and passes them straight
//                                      to removeParents. They are never recorded. The prior NAME
//                                      of a rename is discarded the same way, and no
//                                      untrash/restore path exists anywhere in the repo.
//   api/routes/disposition.py          a Discover-lifecycle candidate (`scan:` doc id) is
//                                      recorded, never executed (#1182).
//
// So ACP cannot offer an undo today for anything, and the honest presentation says where
// recovery lives instead of showing a button that cannot fire.
import { CAN_WRITE_BACK } from './sharepointScopes.js'

/** What is knowable about reversing an action. Four states, and two of them are not failures. */
export const RECOVERY = {
  NOT_EXECUTED: 'not_executed',   // no source action is performed at all, so there is nothing to reverse
  TRASH: 'trash',                 // moved to the source's trash: reversible BY THE USER, at the source
  NO_RECORDED_BEFORE: 'no_before', // performed, but ACP kept no before-state, so ACP cannot reverse it
  UNSUPPORTED: 'unsupported',     // the connector cannot perform this action, so it never happens
  UNKNOWN: 'unknown',             // the source was not supplied — say so, never guess
}

/** Retention windows ACP actually knows. Anything absent is UNKNOWN and must be said as such. */
const WINDOWS = {
  // The only window stated anywhere in this system: api/disposition.py's own detail string for a
  // Drive trash. Recorded here as ACP'S CLAIM rather than as Google's policy, because that is
  // what it is — nothing reads it back from the Drive API.
  drive: 'about 30 days',
}

/** Actions that never touch a file, whatever the source. */
const METADATA_ONLY = new Set(['tag', 'leave'])

/**
 * What can be said about recovering `action` on a file from `source`.
 *
 * `executed` is the caller's knowledge of whether a source action actually happens: false for
 * every Discover-lifecycle candidate today. Left undefined it is treated as UNKNOWN rather than
 * assumed either way — the deliveryPolicy rule again.
 */
export function recoveryFor({ action, source, executed } = {}) {
  const src = String(source || '').toLowerCase()
  const act = String(action || '').toLowerCase()

  if (METADATA_ONLY.has(act)) {
    return { state: RECOVERY.NOT_EXECUTED, window: null, undoInAcp: false,
             summary: 'No file is moved, renamed or trashed — this action only records metadata.' }
  }
  if (executed === false) {
    return { state: RECOVERY.NOT_EXECUTED, window: null, undoInAcp: false,
             summary: 'No source action is performed, so there is nothing to recover. '
                    + 'The decision is recorded against the file.' }
  }
  // An unsupplied source is UNKNOWN, never Drive. The first draft of this fell through to the
  // Drive branch and would have told a reviewer their file was "recoverable for about 30 days"
  // on the strength of a source nobody had stated — inventing the one fact this module exists to
  // avoid inventing. The queue genuinely does not know: source is a property of the scan, not of
  // an inventory row.
  if (!src) {
    return { state: RECOVERY.UNKNOWN, window: null, undoInAcp: false,
             summary: 'The source of this file was not supplied, so what happens to it at the '
                    + 'source — and how it would be recovered — cannot be stated here.' }
  }
  // SharePoint and OneDrive: ACP holds read-only scopes, so the action cannot happen at all.
  // Saying "recoverable from the recycle bin" here would describe a deletion ACP never performs.
  if (src === 'sharepoint' || src === 'onedrive') {
    return { state: RECOVERY.UNSUPPORTED, window: null, undoInAcp: false,
             summary: CAN_WRITE_BACK
               ? 'This deployment can write to SharePoint, but no recovery details are recorded for it.'
               : 'ACP has read-only access to SharePoint and OneDrive, so it never moves, renames '
               + 'or deletes a file there. Nothing is performed, and nothing needs recovering.' }
  }
  if (src !== 'drive') {
    return { state: RECOVERY.UNSUPPORTED, window: null, undoInAcp: false,
             summary: `ACP can only action Google Drive files; a ${src} file is left untouched.` }
  }
  if (act === 'delete') {
    return { state: RECOVERY.TRASH, window: WINDOWS.drive, undoInAcp: false,
             summary: 'Moved to Google Drive trash, never deleted permanently. Restore it from '
                    + "Drive's own trash — ACP cannot restore it for you." }
  }
  if (act === 'archive' || act === 'move' || act === 'rename') {
    // The connector could reverse this; ACP cannot, because it discards the before-state.
    return { state: RECOVERY.NO_RECORDED_BEFORE, window: null, undoInAcp: false,
             summary: act === 'rename'
               ? 'The file is renamed in place. ACP does not record the previous name, so it '
               + 'cannot rename it back — use Drive’s version history.'
               : 'The file is moved, not deleted. ACP does not record where it came from, so it '
               + 'cannot move it back — use Drive’s activity history to find its previous folder.' }
  }
  return { state: RECOVERY.UNSUPPORTED, window: null, undoInAcp: false,
           summary: `No recovery information is recorded for the action ${action || '(none)'}.` }
}

/** One line for a reviewer, naming the window only when one is actually known. */
export function recoveryLine(recovery) {
  if (!recovery) return ''
  return recovery.window
    ? `${recovery.summary} Recoverable for ${recovery.window}.`
    : recovery.summary
}

/**
 * Whether an Undo control may be offered. Always false today, and derived rather than hardcoded
 * so it turns itself on when the before-state is recorded — the same trick CAN_WRITE_BACK uses.
 */
export function canUndo(recovery) {
  return Boolean(recovery && recovery.undoInAcp)
}
