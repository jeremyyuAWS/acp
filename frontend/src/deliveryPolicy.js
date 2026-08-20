// R11 · Delivery — where a remediated file actually ends up.
//
// This is the highest-risk copy in the Remediate redesign, because every sentence it produces is a
// promise about the customer's OWN storage, and it will be read back to us. So the wording lives
// here, as pure functions with tests, rather than inline in JSX where nobody can pin it.
//
// GROUND TRUTH — verified against the tree, not against a design board:
//
//   api/handlers.py:657-661   Blob is the PRIMARY, must-succeed write. `_blob.upload_remediated`
//                             runs on every successful remediation, needs no per-user token
//                             (managed identity), and is what makes the copy durable. This half
//                             is unconditional.
//   api/handlers.py:667       `if core.store.get_drive_mirror_enabled():` — the Drive mirror is a
//                             CONDITIONAL second write, gated on a setting.
//   api/store.py:4015-4020    get_drive_mirror_enabled() is
//                             `get_setting("drive_mirror_enabled", "true") != "false"` — it
//                             DEFAULTS TO TRUE. Under the shipped default a successful
//                             remediation IS auto-mirrored into the source Drive.
//   api/store.py:4025-4028    get_drive_mirror_folder() defaults to "Remediated" and is
//                             admin-configurable, so the folder name is never hardcoded here.
//   api/handlers.py:672-703   the mirror write is files().create into `folder_id` (the mirror
//                             folder), or files().update of a file ALREADY IN that folder — an
//                             upsert against the previous mirrored copy. The source item id is
//                             never a write target on this path.
//   api/handlers.py:450-494   `_remediate_file` requires a `drive_file_id` and a Drive token: the
//                             automatic mirror is a DRIVE-source behaviour and must not be
//                             claimed for anything else.
//   frontend/src/sharepointScopes.js:22-24  this build holds no *.ReadWrite scope, so
//                             CAN_WRITE_BACK is false and ACP never writes to SharePoint at all.
//
// THREE RULES this module exists to enforce:
//
//   1. Never render "nothing is written to your drive". Under the shipped default that sentence is
//      FALSE. A draft board carried it and it had to be corrected.
//   2. State the copy-not-in-place guarantee UNCONDITIONALLY; state the DESTINATION as a function
//      of the setting.
//   3. When the setting has not been read, say nothing about it. An unread setting is MIRROR.UNREAD
//      — not `false`, and not a count of zero. Publish.jsx seeds its settings state to
//      `{ drive_mirror_enabled: false }` and so describes an unread platform as a mirror-off one;
//      that is the mistake this module refuses to make.
import { CAN_WRITE_BACK } from './sharepointScopes.js'

// The mirror setting has three states, and the third is not a boolean.
export const MIRROR = {
  ON: 'on',          // read, and enabled — a Drive copy IS written
  OFF: 'off',        // read, and disabled — Blob only
  UNREAD: 'unread',  // not read yet, or the read failed — we know nothing and say nothing
}

// api/store.py:4028 — the backend's own default, used only once the setting has actually been read.
export const DEFAULT_MIRROR_FOLDER = 'Remediated'

/**
 * Which of the three states the platform settings are in.
 *
 * `null`/`undefined` settings (not fetched, or the fetch failed) and a missing or non-boolean
 * `drive_mirror_enabled` all mean UNREAD. Only a real boolean produces ON or OFF, so a settings
 * object that arrived without the key can never be mistaken for a disabled mirror.
 */
export function mirrorState(settings) {
  if (!settings || typeof settings !== 'object') return MIRROR.UNREAD
  const v = settings.drive_mirror_enabled
  if (v === true) return MIRROR.ON
  if (v === false) return MIRROR.OFF
  return MIRROR.UNREAD
}

/**
 * The mirror folder name, or `null` when the setting has not been read.
 *
 * `null` is the point: a caller that wants to name the folder has to handle not knowing it, rather
 * than printing "Remediated" over an unread setting. GET /settings returns
 * `drive_mirror_enabled` and `drive_mirror_folder` together (api/routes/system.py:560-563), so once
 * the enabled flag is a real boolean the folder default is the backend's own (store.py:4028), not a
 * guess.
 */
export function mirrorFolder(settings) {
  if (mirrorState(settings) === MIRROR.UNREAD) return null
  const raw = typeof settings.drive_mirror_folder === 'string' ? settings.drive_mirror_folder.trim() : ''
  return raw || DEFAULT_MIRROR_FOLDER
}

/**
 * Where this document came from, which decides whether the automatic mirror applies to it at all.
 *
 * 'drive'      — has a drive_file_id: the only source `_remediate_file` will mirror (handlers.py:459).
 * 'sharepoint' — listed from a site/library.
 * 'other'      — local upload, or a record that never carried a source id.
 */
export function sourceKind(file) {
  if (!file || typeof file !== 'object') return 'other'
  if (file.drive_file_id) return 'drive'
  if (file.sp_item_id || file.item_id || file.drive_id) return 'sharepoint'
  if (typeof file.source === 'string' && file.source.toLowerCase() === 'sharepoint') return 'sharepoint'
  if (typeof file.source === 'string' && file.source.toLowerCase() === 'drive') return 'drive'
  return 'other'
}

/**
 * What will actually happen to one document's corrected copy.
 *
 * `durableCopy` is always true — the Blob write is the must-succeed one (handlers.py:659).
 * `mirror` is MIRROR.ON/OFF/UNREAD for Drive-sourced files, and MIRROR.OFF for everything else,
 * because the automatic mirror is a Drive-source behaviour and simply does not apply — that is a
 * fact about the code path, not a reading of the setting, so it stays definite even when the
 * setting is unread. `mirrorApplies` distinguishes the two.
 */
export function fileDelivery(file, settings) {
  const kind = sourceKind(file)
  const mirrorApplies = kind === 'drive'
  const state = mirrorState(settings)
  return {
    file: file?.file ?? null,
    kind,
    mirrorApplies,
    mirror: mirrorApplies ? state : MIRROR.OFF,
    folder: mirrorApplies ? mirrorFolder(settings) : null,
    durableCopy: true,
    // Whether an operator could later choose to put this copy over the original. Drive has a
    // real, shipped replace path (GoogleDrive.jsx DriveUploadButton). SharePoint's is gated on a
    // write scope this build does not request, so for SharePoint it is false and stays false
    // until sharepointScopes.js changes.
    replaceAvailable: kind === 'drive' || (kind === 'sharepoint' && CAN_WRITE_BACK),
  }
}

/**
 * The one-line destination for a single document.
 *
 * Every branch names the durable copy, because that half is true in every configuration. Only the
 * Drive clause moves with the setting, and the UNREAD branch makes no claim in either direction.
 */
export function destinationLine(delivery) {
  const d = delivery || {}
  if (!d.mirrorApplies) {
    return d.kind === 'sharepoint'
      ? 'A corrected copy in ACP storage, to download from here. This deployment connects to SharePoint read-only, so ACP does not write to the library.'
      : 'A corrected copy in ACP storage, to download from here.'
  }
  if (d.mirror === MIRROR.ON) {
    return `A corrected copy in ACP storage, and a second copy in the “${d.folder}” folder of the same Drive, alongside the original.`
  }
  if (d.mirror === MIRROR.OFF) {
    return 'A corrected copy in ACP storage, to download from here. The Drive mirror is switched off, so this remediation adds no file to the Drive folder the original sits in.'
  }
  return 'A corrected copy in ACP storage, to download from here. Whether a copy is also written into your Drive depends on the mirror setting, which has not been read yet.'
}

/**
 * The short destination label for a per-file row. `null` folder is never interpolated.
 */
export function destinationLabel(delivery) {
  const d = delivery || {}
  if (!d.mirrorApplies) return 'ACP storage'
  if (d.mirror === MIRROR.ON) return `ACP storage + Drive “${d.folder}”`
  if (d.mirror === MIRROR.OFF) return 'ACP storage'
  return 'ACP storage + Drive: not known yet'
}

/**
 * The guarantee that does not move. Held as a constant because it is the sentence that must read
 * identically in all three mirror states — the moment it varies with configuration it stops being
 * a guarantee and becomes a description.
 *
 * Scoped precisely to remediation. ACP produces corrected bytes and writes them somewhere NEW; the
 * source document is not opened for writing on that path (handlers.py:450-747). Putting a corrected
 * copy over the original is a separate thing an operator starts by hand, and `replaceNote` below
 * describes it rather than letting this sentence quietly cover it.
 */
export const COPY_GUARANTEE =
  'Remediation works on a copy. Your original document is not edited in place — whatever ACP writes, the source file is left exactly as it was.'

/**
 * What replacing an original would involve, for the sources where that action exists at all.
 * Returns null when no source in the batch offers it, so the UI shows nothing rather than
 * explaining an action nobody can take.
 */
export function replaceNote(deliveries = []) {
  const list = (deliveries || []).filter(Boolean)
  if (!list.some((d) => d.replaceAvailable)) return null
  return 'Putting a corrected copy over the original is a separate action, started per document, and never part of remediation. When you do start it, ACP copies the original into “_mova-originals” first and abandons the write if that copy fails.'
}

/**
 * Batch-level counts for the delivery header.
 *
 * `toDrive` is `null`, NOT `0`, when the mirror setting has not been read and Drive-sourced files
 * are present. A number there would be a measurement; there is nothing to measure until the
 * setting arrives, and rendering `0` would tell the operator their files are staying out of Drive
 * when in fact the shipped default puts them in it.
 */
export function deliverySummary(files = [], settings) {
  const deliveries = (files || []).filter(Boolean).map((f) => fileDelivery(f, settings))
  const state = mirrorState(settings)
  const driveSourced = deliveries.filter((d) => d.mirrorApplies).length
  let toDrive
  if (driveSourced === 0) toDrive = 0             // measured: no file in this batch can be mirrored
  else if (state === MIRROR.ON) toDrive = driveSourced
  else if (state === MIRROR.OFF) toDrive = 0
  else toDrive = null                             // unread — absent, not zero
  return {
    total: deliveries.length,
    // Every remediated file gets the durable copy; that is the must-succeed write.
    toDurableCopy: deliveries.length,
    driveSourced,
    toDrive,
    mirror: state,
    folder: mirrorFolder(settings),
    deliveries,
  }
}

/**
 * The batch destination sentence for the panel header. Mirrors `destinationLine`'s discipline at
 * the group level: the durable copy is stated flatly, the Drive clause tracks the setting, and an
 * unread setting produces a sentence that claims nothing about Drive.
 */
export function summaryLine(summary) {
  const s = summary || {}
  const n = s.total || 0
  const docs = `${n} corrected ${n === 1 ? 'copy' : 'copies'}`
  if (!s.driveSourced) return `${docs} in ACP storage, to download from here.`
  if (s.mirror === MIRROR.ON) {
    return `${docs} in ACP storage. ${s.toDrive} of them ${s.toDrive === 1 ? 'is' : 'are'} also written into the “${s.folder}” folder of the Drive ${s.toDrive === 1 ? 'it came' : 'they came'} from.`
  }
  if (s.mirror === MIRROR.OFF) {
    return `${docs} in ACP storage. The Drive mirror is switched off, so no copy is added to the Drive folders these documents sit in.`
  }
  return `${docs} in ACP storage. Whether copies are also written into your Drive depends on the mirror setting, which has not been read yet.`
}
