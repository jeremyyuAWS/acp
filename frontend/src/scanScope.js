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

// The SharePoint sites a scan covered, newest shape first.
//
// `scope.sites` is `[{id, name}, …]` and is written whenever any site was chosen — including a
// one-site run, so a reader can ask one question instead of branching on how many there were.
// `scope.site`/`site_name` remain the singular spelling and are all that exists on every scan
// recorded before multi-site: read them as a list of one rather than treating a historical run
// as boundary-less, which would render its count with no boundary at all — the defect at the top
// of this file.
export function scopeSites(scope) {
  if (!scope) return []
  if (Array.isArray(scope.sites) && scope.sites.length) {
    return scope.sites.filter(Boolean).map((s) => ({
      id: s.id, name: s.name || null, status: s.status || null,
      listed: Number.isFinite(s.listed) ? s.listed : null,
    }))
  }
  return scope.site ? [{ id: scope.site, name: scope.site_name || null,
                         status: null, listed: null }] : []
}

// SELECTED is not COVERED, and the difference is the whole point of recording a status per site.
// A site the token could not read, or that the cap or the file budget never reached, is still on
// the scope — that is what makes "no site was silently omitted" checkable — but naming it in the
// boundary would claim its documents were counted. So the label reads the covered set and the
// sentence reports the rest.
//
// A row with NO status is a scan recorded before per-site statuses existed, or the singular
// `site` read as a list of one. Those were all covered, by construction: the run had one site
// and it completed or the scan failed outright.
const UNREAD = new Set(['blocked', 'skipped'])
export const scopeSitesCovered = (scope) => scopeSites(scope).filter((s) => !UNREAD.has(s.status))
export const scopeSitesUnread = (scope) => scopeSites(scope).filter((s) => UNREAD.has(s.status))

// Names for a phrase, in the reader's terms: “Finance”, “HR” — falling back to the count when
// Graph would not hand over a display name (a token can read a site's drives while the tenant
// refuses the site metadata read; see scanner._sp_site_name).
const siteNames = (scope) => scopeSitesCovered(scope).map((s) => s.name).filter(Boolean)

// Does this scan admit to a boundary narrower than "your whole estate"? Drives the callout —
// the case a reader needs told, rather than merely available.
export function isNarrowScope(scope) {
  if (!scope) return false
  // A single SharePoint site is exactly as narrow as a single Drive folder, and the site picker
  // (#167) made it a thing an operator does in one click. Before this it read as whole-estate:
  // scanning one site and then OneDrive produced two counts with the same caption, which is the
  // incident at the top of this file with the source swapped.
  //
  // Fixed in BOTH SPAs even though only the redesign had the picker: the scan lands in scan_runs,
  // and frontend/ renders the same row from the same column. A scan started in one app and read
  // in the other is the case where a stale label is least likely to be questioned.
  // A file-type scope that actually excluded something belongs here for the same reason a
  // folder does: the count on screen is smaller than the estate, and the reader needs telling.
  //
  // Gated on the COUNT, not on the setting. A `.docx` scope over an all-Word estate excluded
  // nothing, so the number IS the estate and a ⚠ there would be a warning about nothing —
  // which is how a callout stops being read. `skipped_out_of_scope > 0` is the difference
  // between "narrowed" and "narrowed and it mattered".
  // A chosen-folder SET narrows every source it applies to, and it is checked FIRST because the
  // clauses after it do not cover it. A OneDrive folder scan has kind 'sharepoint' and NO site —
  // so without this, picking three OneDrive folders produced a count with no ⚠ and no boundary:
  // the 2026-07-30 defect at the top of this file, with the source swapped again. A new
  // narrowing mode gets to re-introduce it for free unless it says so here.
  if (Array.isArray(scope.folders) && scope.folders.length > 0) return true
  // `scopeSites(...).length`, not `scope.site`: a MULTI-site run has no singular `site`, so
  // keying off that field alone made a three-site scan — a narrower boundary than one site is
  // wide — render with no ⚠ and no boundary, exactly as a whole-tenant scan would. Thirty sites
  // out of a tenant's four hundred is still not "your estate".
  return (scope.kind === 'folder' || scopeSites(scope).length > 0 || !!scope.truncated
          || (Number(scope.skipped_out_of_scope) || 0) > 0)
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
    case 'folder': {
      // Several chosen folders name themselves rather than collapsing to "in 3 Drive folders":
      // the reader's question is WHICH parts of the estate this covers, and a bare count answers
      // "how many boundaries" instead — the same substitution of a number for a boundary this
      // module exists to stop.
      const named = (scope.folders || []).map((f) => f && f.name).filter(Boolean)
      if (named.length > 1) return `in the Drive folders ${named.map((n) => `“${n}”`).join(', ')}`
      return (scope.folder_name || named[0])
        ? `in the Drive folder “${scope.folder_name || named[0]}”`
        : 'in one Drive folder'
    }
    case 'drive':
      return 'across your whole Google Drive'
    case 'sharepoint':
      // Two different boundaries share this kind. Without a site the scan read the signed-in
      // user's OneDrive, as it always has; with one it read every document library on that site
      // and nothing else. Calling both "across OneDrive" named the wrong source AND claimed the
      // whole of it.
      {
        // Chosen folders beat both readings below: with folders picked this is neither "across
        // your OneDrive" nor "one site" — it is those folders, and either of the others claims a
        // boundary the scan did not have.
        const picked = (scope.folders || []).map((f) => f && f.name).filter(Boolean)
        if (picked.length) {
          const where = scope.site_name ? ` on “${scope.site_name}”` : ' in OneDrive'
          return `in ${picked.map((n) => `“${n}”`).join(', ')}${where}`
        }
      }
      {
        // Sites NAME THEMSELVES rather than collapsing to "across 3 SharePoint sites", for the
        // same reason chosen Drive folders do above: the reader's question is WHICH parts of the
        // estate this covers, and a bare count answers "how many boundaries" instead.
        const selected = scopeSites(scope)
        if (!selected.length) return 'across your OneDrive'
        const sites = scopeSitesCovered(scope)
        // Every selected site unreadable. "In 0 sites" is the honest phrase and the one a reader
        // can act on; naming the sites that were asked for would claim documents were counted in
        // them, which is the direction that overstates coverage.
        if (!sites.length) return `in 0 of ${selected.length} selected SharePoint sites`
        const named = siteNames(scope)
        if (sites.length === 1) {
          return named[0] ? `in the SharePoint site “${named[0]}”` : 'in one SharePoint site'
        }
        // A partly-named set says how many it could not name rather than listing a shorter set
        // as though it were the whole boundary.
        if (named.length === sites.length) {
          return `in the SharePoint sites ${named.map((n) => `“${n}”`).join(', ')}`
        }
        return named.length
          ? `in ${sites.length} SharePoint sites, including ${named.map((n) => `“${n}”`).join(', ')}`
          : `in ${sites.length} SharePoint sites`
      }
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
  if (scope.kind === 'sharepoint' && Array.isArray(scope.folders) && scope.folders.length) {
    // The counterpart of the folder clause below, unconditional for the same reason: at any
    // size, chosen folders are not the estate.
    s += ' Documents in other folders were not scanned.'
  }
  if (scope.kind === 'folder') {
    // The actual missing sentence from the incident. Said unconditionally for a folder scan,
    // including a folder with many files in it: the reader's question is "is this my estate?",
    // and the answer is no at every size.
    s += ` Documents elsewhere in your Drive were not scanned${
      scope.folders_walked > 1 ? `; this folder and its ${scope.folders_walked - 1} subfolder${scope.folders_walked === 2 ? '' : 's'} were` : ''
    }.`
  }
  if (scope.kind === 'sharepoint' && scopeSites(scope).length) {
    // The folder clause's counterpart, and unconditional for the same reason: the reader's
    // question is "is this my estate?", and a chosen set of sites is not, at any size or count.
    // Said as "other sites" rather than "your whole SharePoint" because there is still no scan
    // that covers every site — the selection is capped (ACP_SP_MAX_SITES) — so promising a wider
    // one would be a lie about a button that does not exist.
    s += ' Documents on other SharePoint sites, and in your OneDrive, were not scanned.'
  }
  if (scope.kind === 'sharepoint') {
    // WHY the listing is a floor, which `truncated` alone does not say. The distinction the
    // operator acts on: this is not a file cap they can wait out, it is sites that were never
    // read — because the token could not, or because the site cap or the file budget stopped
    // short — and the fix is a permission, a higher limit, or a second scan.
    //
    // Falls back to `sites_omitted` for a scan recorded before per-site statuses existed, where
    // the count is all there is.
    const unread = scopeSitesUnread(scope)
    const n = unread.length || Number(scope.sites_omitted) || 0
    if (n > 0) {
      const named = unread.map((x) => x.name).filter(Boolean)
      s += ` ${n} further site${n === 1 ? '' : 's'} you selected ${
        n === 1 ? 'was' : 'were'} not read${
        named.length === n ? ` (${named.map((x) => `“${x}”`).join(', ')})` : ''
      }, so this is a floor rather than the whole selection.`
    }
  }
  // An exclusion makes the scan cover LESS than its included paths imply. Two runs of the same
  // folder, one with an Archive carve-out, otherwise render identical boundaries and different
  // counts — the 2026-07-30 defect one level down.
  const nExcl = Array.isArray(scope.excluded) ? scope.excluded.length : 0
  if (nExcl) {
    s += ` ${nExcl} folder${nExcl === 1 ? ' was' : 's were'} excluded from within that selection.`
  }
  if (scope.truncated) {
    s += ` This scan hit its ${
      Number.isFinite(scope.cap) ? scope.cap.toLocaleString() + '-file ' : ''
    }limit before listing everything, so there are more documents it did not see.`
  }
  // Files the FILE-TYPE scope kept ACP from opening at all. Said as "not read", not "excluded":
  // the operator's own setting caused it, and the load-bearing fact is that the content was
  // never opened, rasterised, OCR'd or cached — which is the whole point of scoping the scan for
  // a customer whose documents are PHI.
  //
  // Reported rather than left implicit because narrowing the scope makes the estate SMALLER, and
  // a reader who cannot see why cannot tell a scoped scan from a source that lost files. That
  // shape — a number that changed for a reason nobody could see — is the incident this whole
  // module exists because of. It is also the sentence that answers "did you look at everything?"
  // in an audit, where the honest answer is "no, deliberately, and here is how many".
  const skipped = Number(scope.skipped_out_of_scope) || 0
  if (skipped > 0) {
    s += ` ${skipped.toLocaleString()} ${plural(skipped)} of other file types ${
      skipped === 1 ? 'was' : 'were'} not read, because the scan is scoped by file type.`
  }
  return s
}

// A short chip for lists where a whole sentence will not fit (the scan picker, trend rows).
// Every scan is labelled, including the wide ones — a label that appears only on narrow scans
// is invisible exactly when a reader is comparing two scans and needs to spot the odd one.
export function scopeChip(scope) {
  if (!scope) return null
  if (scope.kind === 'folder') {
    const picked = (scope.folders || []).map((f) => f && f.name).filter(Boolean)
    if (picked.length > 1) return { text: `📁 ${picked.length} folders`, narrow: true }
    const only = scope.folder_name || picked[0]
    return { text: only ? `📁 ${only}` : '📁 one folder', narrow: true }
  }
  // A folder-narrowed SharePoint/OneDrive scan, which has no `site` to be labelled by. Placed
  // before the site branch so a folder inside a site is named by the folder, the tighter bound.
  if (scope.kind === 'sharepoint' && Array.isArray(scope.folders) && scope.folders.length) {
    const picked = scope.folders.map((f) => f && f.name).filter(Boolean)
    return { text: picked.length > 1 ? `📁 ${picked.length} folders`
                                     : `📁 ${picked[0] || 'one folder'}`, narrow: true }
  }
  // Before `truncated`, because a site scan that also hit its cap is still most usefully
  // identified by WHICH site — the folder branch above takes the same precedence for the same
  // reason, and `truncated` still reaches the sentence and the ⚠ either way.
  {
    const selected = scopeSites(scope)
    if (scope.kind === 'sharepoint' && selected.length) {
      const covered = scopeSitesCovered(scope)
      // "2 of 3 sites" in a list row, because the scan-history table is exactly where a partial
      // estate scan gets compared against a complete one and read as a shrinking estate.
      if (selected.length > 1) {
        return { text: covered.length === selected.length
          ? `🏢 ${selected.length} sites`
          : `🏢 ${covered.length} of ${selected.length} sites`, narrow: true }
      }
      return { text: selected[0].name ? `🏢 ${selected[0].name}` : '🏢 one site', narrow: true }
    }
  }
  if (scope.truncated) return { text: 'partial listing', narrow: true }
  if (scope.kind === 'drive') return { text: 'whole Drive', narrow: false }
  if (scope.kind === 'sharepoint') return { text: 'OneDrive', narrow: false }
  if (scope.kind === 'local') return { text: 'local corpus', narrow: false }
  return null
}
