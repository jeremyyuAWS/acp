// Google Drive appends " (1)", " (2)"… when the same file is uploaded more than once — and
// the scanner disambiguates literal same-named files the same way (api/scanner.py
// _dedupe_names, since Drive allows two files to share an identical name, unlike a
// filesystem). Strip the suffix to recover the logical document name.
export const baseName = (name) => name.replace(/ \(\d+\)(\.[^.]+)$/, '$1')

// Collapse duplicate uploads into one representative row per logical document, carrying a
// copy count + the list of actual file names. Shared by Dashboard's File Inventory and
// Discover's Classify summary — don't fork this logic, both need to agree on what counts
// as a duplicate.
export function groupDuplicates(files) {
  const map = new Map()
  for (const f of files) {
    const k = baseName(f.file)
    const g = map.get(k)
    if (!g) { map.set(k, { rep: f, copies: 1, names: [f.file] }) }
    else { g.copies += 1; g.names.push(f.file); if (f.file === k) g.rep = f }
  }
  return [...map.values()].map((g) => ({ ...g.rep, _copies: g.copies, _names: g.names }))
}

// How many of `files` are extra copies of a logical document (i.e. files.length minus the
// number of distinct logical documents).
export const dupeCountOf = (files) => files.length - groupDuplicates(files).length

// Every file (ALL copies, not just the representative) that belongs to a logical document
// with more than one copy — for drilling into "which files are these duplicates", not just
// a count.
export function duplicateFiles(files) {
  const counts = new Map()
  for (const f of files) { const k = baseName(f.file); counts.set(k, (counts.get(k) || 0) + 1) }
  return files.filter((f) => counts.get(baseName(f.file)) > 1)
}
