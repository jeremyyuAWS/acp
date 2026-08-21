// Did any classification actually reach this screen?
//
// Discover carries a whole triage surface — documents grouped by DEPARTMENT, chips for PII /
// legal-hold / public-facing / high-traffic, a "By exposure & risk" chart, and a confirm-or-correct
// workflow with "✓ accept both". On the SIM estate every one of those is populated. On a REAL scan
// none of it is, and the screen does not say so.
//
// VERIFIED IN THE TREE, 2026-08-21, not inferred from behaviour:
//
//   store.py:70      `file_records` has no `department`, no `tags`, no sensitivity column.
//   store.py:1752    `get_scan` projects file_records alone — nothing joins `documents`, which is
//                    the only table carrying `department`.
//   store.py:4647    "ADR 0003 notes department has no scan-derived source yet, so on most
//                    estates that bucket IS the estate."
//   store.py:1902    "department is not on scan_inventory today, so department-selector rules do
//                    not resolve at this layer."
//
// So `f.department` is undefined for every real file and `f.tags` is empty. The estate renders as
// one "Unassigned" group of 12,408 documents, an exposure chart reading 100% internal with every
// risk flag at zero, and a tagging workflow with nothing to confirm.
//
// EVERY ONE OF THOSE NUMBERS IS TRUE AND THE READING IS FALSE. "0 legal-hold" states that the
// estate contains no documents under legal hold — a finding nobody obtained, on a screen a
// compliance reader is looking at precisely to find them. That is the same defect as
// `hasLifecycleData`, which this file deliberately mirrors:
//
//     False means the recommendation surface must be OMITTED, not zeroed.
//
// Absent is the honest answer. A zero is a measurement.

/** The classification tags Discover offers. Mirrors CLASS_TAGS in Discover.jsx — the two are the
 *  same list on purpose, and a tag present here but not there would silently never be counted. */
export const CLASSIFICATION_TAGS = ['PII', 'legal-hold', 'public-facing', 'high-traffic']

const CLASS_SET = new Set(CLASSIFICATION_TAGS)

/** Does this row carry a department a scan actually recorded? Empty strings are not departments. */
export const hasDepartment = (f) =>
  !!(f && typeof f.department === 'string' && f.department.trim() !== '')

/** Does this row carry at least one classification tag? Status tags (certified, needs-review …)
 *  are NOT classification and must not make an unclassified estate look classified. */
export const hasClassTag = (f) =>
  Array.isArray(f && f.tags) && f.tags.some((t) => CLASS_SET.has(t))

/**
 * Did classification reach this screen at all?
 *
 * `null` when `files` is not an array — nothing was read, so nothing is claimed. Otherwise an
 * object saying WHICH half arrived, because they have different sources and can arrive apart: a
 * future scan-derived department would light `department` while tags stayed empty.
 *
 * `any` is what gates the surface. It is deliberately OR, not AND: a screen with departments and
 * no tags still has something true to show.
 */
export function classificationCoverage(files) {
  if (!Array.isArray(files)) return null
  const department = files.filter(hasDepartment).length
  const tagged = files.filter(hasClassTag).length
  return {
    total: files.length,
    department,
    tagged,
    any: department > 0 || tagged > 0,
  }
}

/** True when the triage surface should render. Sugar over `classificationCoverage`, so a caller
 *  cannot accidentally treat a null (nothing read) as false (read, and empty) — those are
 *  different facts and collapsing them is how "we did not look" becomes "there is nothing there". */
export const hasClassificationData = (files) => {
  const c = classificationCoverage(files)
  return !!(c && c.any)
}

/** What to say instead, when nothing classified this estate.
 *
 *  Names the MECHANISM rather than apologising. A reader who is told "no classification data" asks
 *  whether the scan failed; a reader told the scan does not collect it yet knows it is a gap in the
 *  product, not in their estate or their run — and knows not to wait for it by re-scanning.
 */
export const NO_CLASSIFICATION_TITLE = 'This estate is not classified'

export const NO_CLASSIFICATION_BODY =
  'Discovery records names, paths, sizes and dates. It does not yet derive a department or a '
  + 'sensitivity label from a document, and no source supplies one, so there is nothing to group '
  + 'or tag by here.'

export const NO_CLASSIFICATION_WHY =
  'Shown as absent rather than as zero: "0 legal-hold" would state that this estate holds no '
  + 'documents under legal hold, which is a finding nobody obtained.'
