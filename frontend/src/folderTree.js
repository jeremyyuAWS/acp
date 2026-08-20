// Tri-state and folder size in a picker that only ever holds ONE level of the tree.
//
// Item 4 of the wizard review asked for tri-state checkboxes and an approximate file count per
// folder. Both are right to want, and both run straight into what this picker can actually know —
// so this module is mostly about drawing that line, because crossing it produces a confident
// number nobody can support.
//
// ── TRI-STATE ──────────────────────────────────────────────────────────────────────────────────
// FolderPicker drills, it does not expand: it holds the current folder's children and the
// breadcrumb, never the whole tree. Its own comment says so — "full PRD tri-state (which needs the
// whole tree to know 'some descendants selected') is not knowable here".
//
// That is true in general and FALSE in one specific case, which happens to be the one that matters:
// a folder you picked, from which you then carved something out. You can only exclude a folder
// while drilling INTO an included ancestor, so at the moment of exclusion the ancestor is known
// exactly. Recording it makes "this folder is partly selected" an exact fact rather than an
// inference — no tree walk, no extra request, no guessing.
//
// So: indeterminate iff the folder is picked AND at least one exclusion was made beneath it.
// Everything else stays binary, which is honest — an unexpanded folder with unknown descendants is
// not "partially selected", it is a folder nobody has looked inside.
//
// ── COUNTS ─────────────────────────────────────────────────────────────────────────────────────
// The review asked for "~120 files". That number does not exist:
//
//   · Google Drive's /folders returns `id` and `name` only — no count of any kind.
//   · SharePoint's returns `child_count`, which is Graph's `folder.childCount`: the number of items
//     DIRECTLY inside, counting subfolders as items, and not recursing.
//
// Rendering childCount as "~120 files" would be wrong twice over — wrong unit (items, not files)
// and wrong depth (this level, not the subtree) — on the screen whose entire job is telling you
// what you are about to scan. A recursive count is a request per folder, which is a real cost for
// a number nobody asked to pay for; and the honest recursive count already exists AFTER a scan, in
// the inventory.
//
// So the count is shown where it exists, labelled as what it is, and omitted where it does not.
// "12 items" is a smaller claim than "~120 files" and it is one we can stand behind.

/**
 * Record which included ancestor a carve-out was made under.
 *
 * `stack` is the breadcrumb at the moment of exclusion, so the nearest picked ancestor is the
 * folder this exclusion narrows. Stored on the exclusion itself because the flat `excluded` list
 * has nowhere else to put it, and because it must survive being handed to the scan.
 */
export function excludeUnder(stack, isPicked) {
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    if (isPicked(stack[i].id)) return stack[i].id
  }
  return null
}

/**
 * Is this folder partly selected — included, with something carved out beneath it?
 *
 * Exact, not heuristic: `under` was recorded at exclusion time from the live breadcrumb.
 * An exclusion with no recorded ancestor (one restored from a saved scope written before this
 * existed) contributes nothing rather than being guessed at.
 */
export function isPartlySelected(folderId, picked, excluded) {
  if (!folderId) return false
  if (!(picked || []).some((p) => p.id === folderId)) return false
  return (excluded || []).some((e) => e && e.under === folderId)
}

/**
 * What one checkbox should render: 'on' | 'off' | 'partial'.
 *
 * `partial` maps to the DOM `indeterminate` property, which cannot be set from markup — the caller
 * sets it on the element. Returning a state rather than a boolean is what keeps that decision in
 * one place instead of duplicated across the two row branches.
 */
export function checkboxState(folder, { picked, excluded, inherited, isExcluded }) {
  if (inherited) return isExcluded(folder.id) ? 'off' : 'on'
  if (isPartlySelected(folder.id, picked, excluded)) return 'partial'
  return (picked || []).some((p) => p.id === folder.id) ? 'on' : 'off'
}

/**
 * The size hint for a row, or null when the provider gave us nothing.
 *
 * Deliberately "items", never "files": Graph's childCount counts subfolders too and does not
 * recurse. Null for Google Drive, which returns no count at all — an absent hint is better than a
 * number that means something different per provider on the same screen.
 */
export function sizeHint(folder) {
  const n = folder && folder.child_count
  if (typeof n !== 'number' || n < 0) return null
  return `${n.toLocaleString()} item${n === 1 ? '' : 's'}`
}

/** Long-form, for the row's title attribute — says what the number is and is not. */
export const SIZE_HINT_BASIS =
  'Items directly inside this folder, including subfolders. Not a recursive file count — '
  + 'the exact number of documents is known after a scan.'
