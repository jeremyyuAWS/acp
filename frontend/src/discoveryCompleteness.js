// Is this inventory the WHOLE estate, or only the part the source was willing to list?
//
// Discovery's entire value is completeness. Everything downstream is a fraction of the number it
// produces — assessment coverage, the reconciliation, the compliance assertion — so an inventory
// that is quietly partial does not produce a small error, it produces a confident wrong answer
// about an estate nobody actually looked at.
//
// Two of the three ways that happens are already surfaced: the listing cap (`isTruncated`, which
// makes `discovered` a floor and is stated as one in three places) and per-file read failures (the
// "could not be read" panel on the results screen). This module is the third, which nothing said:
//
//   THE SOURCE ITSELF CAN UNDER-REPORT, AND IT LOOKS EXACTLY LIKE A SMALL ESTATE.
//
// Verified in the scanner rather than taken from the issue text:
//
//   api/scanner.py:951,956   SharePoint and OneDrive enumerate with Graph `search(q='')`, which
//                            reads the SEARCH INDEX. The index is eventually consistent, so a
//                            recently-changed library is under-reported with no error and no
//                            signal. Issue #333 measured it: 178 files uploaded, 39 discovered,
//                            presented as complete; the same index returned 157 five minutes
//                            later and 158 after fifteen.
//   api/scanner.py:509       Google Drive walks folders directly (`_search_folder`), which is
//                            immediately consistent for whatever the token can see.
//
// So the guarantee is a property of the SOURCE, and stating it is free — no extra call, no
// estimate. What this module will not do is invent the missing half of #333: comparing against the
// library's own `ItemCount` needs a backend call that does not exist yet, so nothing here says
// "39 of ~374". A caveat that is honest about being a caveat beats a number that is made up.

/** How a source enumerates, and what that does and does not guarantee. Null for a source we have
 *  not established — silence rather than a guess about someone's connector. */
export function enumerationMethod(source) {
  if (source === 'sharepoint' || source === 'onedrive') {
    return {
      source,
      method: 'search index',
      consistent: false,
      // Deliberately not "may be incomplete" — that is true of everything and warns nobody. This
      // names the mechanism, so a reader can tell whether it applies to them today.
      caveat: 'SharePoint and OneDrive are listed through Microsoft’s search index, which lags '
            + 'recent changes. Files uploaded or moved shortly before this run may not appear yet, '
            + 'and a partial listing is indistinguishable from a genuinely small estate.',
      resolve: 'If this estate was changed in the last few minutes, list it again before assessing.',
    }
  }
  if (source === 'drive') {
    return {
      source,
      method: 'folder traversal',
      consistent: true,
      caveat: 'Google Drive is listed by walking folders directly, so this reflects the drive as it '
            + 'was at the moment of the run — not a search index that may lag behind it.',
      resolve: null,
    }
  }
  return null
}

/** The discovery count for a scan row, or null.
 *
 *  `scope.inventory.discovered` and NOT `files`. They are different questions and drifted apart in
 *  #550: `files` now counts what ASSESS enqueued, so on an assessed run it is the post-filter
 *  number and on a discover-only run it is the listing. Comparing it across runs would compare a
 *  filtered count against an unfiltered one and report the filter as a change in the estate.
 */
export function discoveredCount(scan) {
  const n = scan && scan.scope && scan.scope.inventory && scan.scope.inventory.discovered
  return typeof n === 'number' && n >= 0 ? n : null
}

/**
 * This run against the previous listing of the SAME source.
 *
 * A run that lists materially fewer files than the last one is either a real deletion or an
 * incomplete listing, and discovery cannot tell which — it only ever sees what it was handed. That
 * ambiguity is the point: naming the drop puts a person on it, where staying silent lets a
 * half-listed estate flow into an assessment and a compliance assertion.
 *
 * Returns null when there is nothing to compare, which is the common case and not a problem.
 *
 * @param run       the current run
 * @param scanList  prior scans, newest first (the /scans list)
 */
export function previousListing(run, scanList) {
  const now = discoveredCount(run)
  if (now == null || !run || !run.source || !Array.isArray(scanList)) return null

  const prior = scanList
    .filter((s) => s && s.id !== run.id && s.source === run.source && discoveredCount(s) != null)
    // completed_at is a string timestamp; newest first.
    .sort((a, b) => String(b.completed_at || '').localeCompare(String(a.completed_at || '')))[0]
  if (!prior) return null

  const was = discoveredCount(prior)
  const delta = now - was
  // A percentage of zero is not a percentage. A previous run that listed nothing makes any current
  // number an infinite increase, which is not a fact worth printing.
  const share = was > 0 ? delta / was : null

  return {
    now,
    was,
    delta,
    share,
    when: prior.completed_at || null,
    priorId: prior.id,
    // MATERIAL means "worth a person's attention", not "wrong". A drop of more than a tenth of the
    // estate is the shape #333 produced (39 where 157 were expected — a 75% drop that nothing
    // mentioned). Growth is never flagged: an estate getting bigger is not a completeness risk.
    dropped: share != null && share <= -0.1,
  }
}

/** What the comparison above can and cannot see.
 *
 *  `list_scans` selects `completed_at IS NOT NULL`, and under ADR 0020 a discover-only run stops at
 *  status='discovered' and leaves that column NULL — possibly forever, if nobody assesses it. So
 *  the comparison set is runs that reached an assessment, and a reader who has listed this source
 *  three times today without assessing will correctly see no comparison rather than a wrong one.
 *
 *  Stated rather than hidden: a caveat a reader cannot see the edge of is not a caveat.
 */
export const COMPARISON_SCOPE =
  'Compared against previous runs of this source that completed an assessment. '
  + 'Listings that were never assessed are not in this history.'
