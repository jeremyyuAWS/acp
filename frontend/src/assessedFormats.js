// "Formats: DOCX, XLSX, PPTX, PDF" — four labels, and no statement of what they are the formats OF.
//
// The scan walks EVERYTHING. In `_sp_list` two lists are built from the same walk:
//
//     est_files.append({...})                    # every item found, whatever its type
//     if Path(name).suffix.lower() in exts:      # .docx .pptx .xlsx .pdf .html .htm
//         files.append(rec)                      # -> inventory row -> assessable later
//
// So a run has three populations, not one:
//
//   1. everything discovered            — the estate; a .zip and a .mov are in here
//   2. the supported extensions         — what becomes a document with an inventory row
//   3. the formats chosen on this run   — what is actually judged against WCAG and remediated
//
// The review step named only (3), as a bare list, in a dialog whose other number is a count of
// (1). A reader reconciling "22 documents" with "DOCX, XLSX, PPTX, PDF" has no way to tell whether
// the four are a filter already applied to the 22, a filter about to be applied, or something else
// entirely — and the reassuring reading is that all 22 get assessed.
//
// Same family as everything else on this screen: a true list, a false conclusion. The fix is not a
// new number, it is saying what the number already there MEANS.

/** The row label. Names the two things these formats decide, in the user's own words. */
export const ASSESSED_ROW_LABEL = 'WCAG assessed & remediated'

/** Formats that ACP can turn into an inventory row at all — `exts` in scanner._sp_list. */
export const SUPPORTED_EXTS = ['docx', 'xlsx', 'pptx', 'pdf', 'html']

/**
 * The chosen formats, rendered, or an explicit empty.
 *
 * "None selected" is kept rather than shown blank: an empty row beside a document count reads as
 * "all of them".
 */
export function assessedFormatsLine(activeFormats, labels = {}) {
  const list = (activeFormats || []).map((f) => labels[f] || String(f).toUpperCase())
  return list.length ? list.join(', ') : 'None selected'
}

/**
 * What happens to everything else.
 *
 * Stated positively about the estate rather than as a warning: the other files are not dropped,
 * they are listed. A reader who thinks unsupported files vanished cannot reconcile the estate
 * count on Discover with the document count here, and will assume one of them is wrong.
 */
export const OTHER_TYPES_NOTE =
  'Every file found is listed in the inventory. Only these formats are opened, judged against '
  + 'WCAG, and remediated — other types are recorded and left unevaluated.'

/**
 * The formats half of the running footer summary.
 *
 * "4 formats" alone reads as a filter on what gets FOUND. It is a filter on what gets JUDGED, and
 * one word fixes it.
 */
export function footerFormatsPart(n) {
  return `${n} format${n === 1 ? '' : 's'} assessed`
}

/**
 * A format the user selected that the scanner cannot produce a row for at all.
 *
 * Empty today — the wizard offers exactly the four the scanner supports. It exists because the two
 * lists live in different languages and nothing connects them: adding a format to the picker
 * without adding its extension to `exts` would silently select something that can never be
 * assessed, and the review step would list it with confidence. Cheap to check, and the check is
 * the only thing that would notice.
 */
export function unscannableFormats(activeFormats) {
  return (activeFormats || []).filter((f) => !SUPPORTED_EXTS.includes(String(f).toLowerCase()))
}
