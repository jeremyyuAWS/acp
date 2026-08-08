// What a scan's document count is a count OF.
//
// A file count is a fact about a boundary, not about an estate. Those are the same number only
// when the boundary is "everything", and the product used to render the count alone — so they
// looked identical.
//
// 2026-07-30, one account, six seconds apart:
//
//   01:38:35  POST /scans?source=drive&folder=1W27ULZ…   →  1 document   (folder subtree)
//   01:38:41  POST /scans?source=drive                   →  8 documents  (whole Drive)
//
// Both listings were correct. The folder held one file; the Drive held eight. The screen said
// "1 documents discovered across 1 sources" and then "8 documents discovered across 1 sources",
// which reads as an estate that shrank, and was reported as a scan losing seven files. Six
// seconds is also what rules out every credential explanation: one token cannot be both
// too narrow to see eight files and wide enough to see eight files.
//
// So the count is never rendered without its boundary. Same failure as the dashboard
// contradictions in #77/#84: the number was right and unaccompanied.
//
// `scope` is scanner._list's scope_out, persisted on scan_runs.scope. It is NULL for scans that
// predate the column — and that case must say NOTHING. "No scope recorded" is not evidence of a
// whole-Drive scan, and defaulting to the reassuring reading is how the original defect
// would come back wearing a label.

const plural = (n) => (n === 1 ? 'document' : 'documents')

// Does this scan admit to a boundary narrower than "your whole estate"? Drives the callout —
// the case a reader needs told, rather than merely available.
export function isNarrowScope(scope) {
  if (!scope) return false
  // A single SharePoint site is exactly as narrow as a single Drive folder, and the site picker
  // (#167) made it a thing an operator does in one click. Before this it read as whole-estate:
  // scanning one site and then OneDrive produced two counts with the same caption, which is the
  // incident at the top of this file with the source swapped.
  //
  // Fixed in BOTH SPAs even though only frontend-v2 has the picker: the scan lands in scan_runs,
  // and frontend/ renders the same row from the same column. A scan started in one app and read
  // in the other is the case where a stale label is least likely to be questioned.
  return scope.kind === 'folder' || !!scope.site || !!scope.truncated
}

// True when the scan hit a cap and there ARE files it did not list. Strictly different from a
// small result: a folder scan that covered its folder completely is not truncated, however few
// documents came back. Conflating the two would put "we could not see everything" on a scan
// that saw everything it was asked to.
export const isTruncated = (scope) => !!(scope && scope.truncated)

// The boundary, as a phrase that completes "<n> documents …".
export function scopeLabel(scope) {
  if (!scope) return null
  switch (scope.kind) {
    case 'folder':
      return scope.folder_name
        ? `in the Drive folder “${scope.folder_name}”`
        : 'in one Drive folder'
    case 'drive':
      return 'across your whole Google Drive'
    case 'sharepoint':
      // Two different boundaries share this kind. Without a site the scan read the signed-in
      // user's OneDrive, as it always has; with one it read every document library on that site
      // and nothing else. Calling both "across OneDrive" named the wrong source AND claimed the
      // whole of it.
      if (!scope.site) return 'across your OneDrive'
      return scope.site_name
        ? `in the SharePoint site “${scope.site_name}”`
        : 'in one SharePoint site'
    case 'local':
      return 'in the local corpus'
    default:
      return null
  }
}

// The full sentence shown beside the count. Returns null when the scope is unknown, so callers
// render nothing rather than a guess.
export function scopeSentence(scope, count) {
  const label = scopeLabel(scope)
  if (!label) return null
  const n = Number.isFinite(count) ? count : (scope.kept ?? 0)
  let s = `${n.toLocaleString()} ${plural(n)} ${label}.`
  if (scope.kind === 'folder') {
    // The actual missing sentence from the incident. Said unconditionally for a folder scan,
    // including a folder with many files in it: the reader's question is "is this my estate?",
    // and the answer is no at every size.
    s += ` Documents elsewhere in your Drive were not scanned${
      scope.folders_walked > 1 ? `; this folder and its ${scope.folders_walked - 1} subfolder${scope.folders_walked === 2 ? '' : 's'} were` : ''
    }.`
  }
  if (scope.kind === 'sharepoint' && scope.site) {
    // The folder clause's counterpart, and unconditional for the same reason: the reader's
    // question is "is this my estate?", and one site is not, at any size. Said as "other sites"
    // rather than "your whole SharePoint" because there is no scan that covers every site —
    // _sp_list takes one site or OneDrive — so promising a wider one would be a lie about a
    // button that does not exist.
    s += ' Documents on other SharePoint sites, and in your OneDrive, were not scanned.'
  }
  if (scope.truncated) {
    s += ` This scan hit its ${
      Number.isFinite(scope.cap) ? scope.cap.toLocaleString() + '-file ' : ''
    }limit before listing everything, so there are more documents it did not see.`
  }
  return s
}

// A short chip for lists where a whole sentence will not fit (the scan picker, trend rows).
// Every scan is labelled, including the wide ones — a label that appears only on narrow scans
// is invisible exactly when a reader is comparing two scans and needs to spot the odd one.
export function scopeChip(scope) {
  if (!scope) return null
  if (scope.kind === 'folder') {
    return { text: scope.folder_name ? `📁 ${scope.folder_name}` : '📁 one folder', narrow: true }
  }
  // Before `truncated`, because a site scan that also hit its cap is still most usefully
  // identified by WHICH site — the folder branch above takes the same precedence for the same
  // reason, and `truncated` still reaches the sentence and the ⚠ either way.
  if (scope.kind === 'sharepoint' && scope.site) {
    return { text: scope.site_name ? `🏢 ${scope.site_name}` : '🏢 one site', narrow: true }
  }
  if (scope.truncated) return { text: 'partial listing', narrow: true }
  if (scope.kind === 'drive') return { text: 'whole Drive', narrow: false }
  if (scope.kind === 'sharepoint') return { text: 'OneDrive', narrow: false }
  if (scope.kind === 'local') return { text: 'local corpus', narrow: false }
  return null
}
