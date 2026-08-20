// Folder picker — drills into a source's folders and hands back the chosen ones. Used by the
// Sources tab (choose the locations a connection scans, saved on the connection), by Discover
// (narrow one scan), and by step 1 of the scan wizard.
//
// FOUR THINGS IT DOES THAT THE SINGLE-FOLDER VERSION DID NOT:
//
// 1. MULTI-SELECT. A real estate is "HR and Finance", not "HR". Selecting one folder at a time
//    forced a choice between scanning too much and running several scans whose counts then have
//    to be added up by hand — and a count you assembled yourself has no boundary recorded on it.
//
// 2. PLUGGABLE LISTER. Drive lists through GET /folders; OneDrive and SharePoint list through
//    GET /sharepoint/folders. The drill-down, selection and "everything inside it" semantics are
//    identical, so they share this component rather than growing a second one that drifts.
//    Graph ids arrive already in `<driveId>/<itemId>` form because a Graph item id is unique only
//    within its drive — the picker never re-assembles that pair itself.
//
// 3. EXCLUSIONS. An unchecked child beneath an included parent is an explicit carve-out, held
//    separately from the inclusions because "not included" and "excluded" are different answers.
//
// 4. TWO LAYOUTS, ONE IMPLEMENTATION. `layout="modal"` is the overlay dialog the Sources card and
//    Discover open; `layout="inline"` is the two-column browser the wizard embeds in step 1 —
//    tree on the left, the scope you have built on the right, both visible at once. They are the
//    same component on purpose: a second picker written for the wizard would drift from this one,
//    and the halves that drift first are the exclusion semantics and the empty-state wording,
//    which are exactly the two places a wrong answer is invisible.
//
// Recursion is automatic server-side (_search_folder / _sp_walk_folder BFS), so there is no
// "include subfolders" toggle: it would be a choice whose wrong answer silently under-reports.
import { useState, useCallback, useEffect, useRef } from 'react'
import { listFolders } from './api.js'
import { INCOMPLETE_LINE } from './wizardScopeReady.js'
import { excludeUnder, checkboxState, sizeHint, SIZE_HINT_BASIS } from './folderTree.js'
import { friendlyFolderError, actionLabel, SKELETON_ROWS } from './folderErrorCopy.js'

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </svg>
  )
}

export default function FolderPicker({
  onScan, onClose, onConfirm, onChange,
  lister = listFolders,
  rootName = 'My Drive',
  initial = [],
  initialExclude = [],
  title = 'Choose folders to scan',
  layout = 'modal',
  // The caller declares whether an empty selection is a legitimate 'everything' (a source
  // card's default) or an unfinished narrowing (the wizard's 'Specific folders'). Asked,
  // never inferred: the two look identical here and only the caller knows which it meant.
  requireSelection = false,
  // Named in the error sentence, so a reader with several connections wired up knows
  // WHICH one failed. Defaults to the neutral phrase rather than guessing a provider.
  sourceName = 'the source',
}) {
  const [stack, setStack] = useState([{ id: 'root', name: rootName }])
  const [folders, setFolders] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('')
  // The running selection, as {id, name} so a chip can NAME the folder. Ids alone would render
  // the chips as opaque Drive/Graph ids, which is not a boundary a reader can check a count
  // against — the same reason scanner resolves folder_name / site_name server-side.
  const [picked, setPicked] = useState(() => initial.map((f) => ({ id: f.id, name: f.name })))
  // Explicit carve-outs beneath an included parent (PRD §6.3). Held separately from `picked`
  // rather than as a negative entry in it, because the two answer different questions and a
  // single list would make "not included" and "explicitly excluded" the same value — which is
  // exactly the distinction the review step has to show.
  const [excluded, setExcluded] = useState(() => initialExclude.map((f) => ({ id: f.id, name: f.name })))
  const current = stack[stack.length - 1]
  const inline = layout === 'inline'

  const load = useCallback((folderId) => {
    setLoading(true); setErr('')
    Promise.resolve(lister(folderId))
      .then((r) => setFolders(r.folders || []))
      .catch((e) => setErr(e.message || 'Failed to load folders'))
      .finally(() => setLoading(false))
  }, [lister])

  useEffect(() => { setFilter(''); load(current.id) }, [current.id, load])

  // The inline layout has no Save button — the wizard's own footer is the only footer — so the
  // selection has to reach the parent as it is made. Reported through a ref so a parent that
  // passes a fresh closure every render (the normal case) does not re-fire this on every render
  // and hand itself its own state straight back mid-update.
  const changeRef = useRef(onChange)
  changeRef.current = onChange
  const firstReport = useRef(true)
  useEffect(() => {
    // Skip the mount report. It would echo `initial` back at a parent that may still be loading
    // its saved value, and overwrite the real selection with an empty list — silent widening,
    // which is the direction nobody re-checks.
    if (firstReport.current) { firstReport.current = false; return }
    if (typeof changeRef.current === 'function') changeRef.current(picked, excluded)
  }, [picked, excluded])

  const enter = (folder) => setStack((s) => [...s, folder])
  const goTo  = (idx)    => setStack((s) => s.slice(0, idx + 1))
  const isPicked = (id) => picked.some((p) => p.id === id)
  const isExcluded = (id) => excluded.some((p) => p.id === id)
  const toggle = (f) => setPicked((s) => (s.some((p) => p.id === f.id)
    ? s.filter((p) => p.id !== f.id)
    : [...s, { id: f.id, name: f.name }]))
  // `under` is the included ancestor this carve-out narrows, read from the LIVE breadcrumb at the
  // moment of exclusion. You can only exclude while drilling inside an included folder, so it is
  // exact here and unknowable later — which is what makes tri-state possible without the tree.
  // Additive: the backend reads id/name and ignores the rest.
  const toggleExclude = (f) => setExcluded((s) => (s.some((p) => p.id === f.id)
    ? s.filter((p) => p.id !== f.id)
    : [...s, { id: f.id, name: f.name, under: excludeUnder(stack, isPicked) }]))
  // Clearing the inclusions clears the carve-outs with them. An exclusion whose parent is gone is
  // not a narrower scope, it is a false line on the review step: the chip says "except Archive"
  // with nothing included for Archive to be an exception to. The backend already drops that pair
  // (drive.py drops exclusions when no inclusions exist), so this is the same rule stated on the
  // surface a user reads rather than a second, quieter one.
  const clearAll = () => { setPicked([]); setExcluded([]) }

  // Is the folder we are looking INSIDE already covered by an inclusion? The tree loads lazily,
  // so full PRD tri-state (which needs the whole tree to know "some descendants selected") is
  // not knowable here — but the BREADCRUMB is the ancestry, and you can only carve out a child
  // while drilling into it. That makes this exact, not approximate: a row is inherited-included
  // iff one of the folders above it in `stack` was picked.
  const inherited = stack.some((a) => isPicked(a.id))

  // What one row's checkbox means, and what unchecking it does. Kept as one function because the
  // two branches are easy to drift apart, and drift here silently converts an exclusion into a
  // no-op — the folder still gets scanned and the chip still says it will not be.
  const rowState = (f) => (inherited
    ? { checked: !isExcluded(f.id), onToggle: () => toggleExclude(f),
        hint: isExcluded(f.id) ? 'excluded' : 'included via parent' }
    : { checked: isPicked(f.id), onToggle: () => toggle(f), hint: null })

  // Multi-select mode is what the Sources tab and the wizard use; Discover still passes onScan and
  // gets the one-folder behaviour it always had, so that call site is unchanged by this growing
  // a mode.
  const multi = inline || typeof onConfirm === 'function'

  // FILTERING IS SCOPED TO THIS FOLDER, AND SAYS SO. It is not a search of the whole Drive: that
  // needs a backend query, and Drive and Graph would answer it differently enough that one would
  // work and the other would quietly return less — an asymmetry a user cannot see. A control
  // labelled "search" that only looks at the rows already on screen is the boundary defect in
  // miniature: the result is correct and the conclusion drawn from it ("no such folder") is wrong.
  const q = filter.trim().toLowerCase()
  const shown = q ? folders.filter((f) => (f.name || '').toLowerCase().includes(q)) : folders

  const breadcrumb = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, marginBottom: 10,
                  flexWrap: 'wrap', color: 'var(--muted)', paddingBottom: 10,
                  borderBottom: '1px solid var(--line)' }}>
      {stack.map((f, i) => (
        <span key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          {i > 0 && <span>›</span>}
          <button type="button" style={{ background: 'none', border: 'none', padding: 0, fontSize: 12,
            cursor: i < stack.length - 1 ? 'pointer' : 'default',
            color: i < stack.length - 1 ? 'var(--accent)' : 'var(--ink)',
            fontWeight: i === stack.length - 1 ? 600 : 400 }}
            onClick={() => i < stack.length - 1 && goTo(i)}>
            {f.name}
          </button>
        </span>
      ))}
    </div>
  )

  const filterBox = (
    <div style={{ marginBottom: 8 }}>
      <input value={filter} onChange={(e) => setFilter(e.target.value)}
             aria-label={`Filter folders in ${current.name}`}
             placeholder={`Filter folders in ${current.name}`}
             style={{ width: '100%', padding: '6px 9px', borderRadius: 8,
                      border: '1px solid var(--line)', background: 'var(--surface)',
                      color: 'inherit', font: 'inherit', fontSize: 12.5 }} />
      {q !== '' && (
        <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
          {shown.length} of {folders.length} in <b>{current.name}</b> — filters this folder only,
          it does not search subfolders.
        </div>
      )}
    </div>
  )

  const list = (
    <div style={{ minHeight: 140, maxHeight: inline ? 260 : 300, overflowY: 'auto',
                  border: '1px solid var(--line)', borderRadius: 10, marginBottom: 14 }}>
      {loading && (
        // Skeleton ROWS, not a centred "Loading…" in an otherwise empty bordered box. That box is
        // the same space where "No subfolders here" appears, so an empty one reads as a stated
        // absence — and a reader who concludes a folder has nothing in it stops narrowing.
        <div aria-busy="true" aria-live="polite" style={{ padding: 6 }}>
          <span className="sronly">Loading folders from {sourceName}…</span>
          {Array.from({ length: SKELETON_ROWS }, (_, i) => (
            <div key={i} aria-hidden="true"
                 style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px' }}>
              <span style={{ width: 14, height: 14, borderRadius: 3, background: 'var(--line)' }} />
              <span style={{ height: 10, borderRadius: 5, background: 'var(--line)',
                             // Varied widths so it reads as content arriving rather than as a
                             // progress bar that is stuck.
                             width: `${52 - (i % 3) * 11}%`, opacity: 1 - i * 0.13 }} />
            </div>
          ))}
        </div>
      )}
      {err && (() => {
        // The raw provider error used to be the whole message. It read as a broken product, leaked
        // drive ids and internal URL shape onto the screen, and told nobody what to do. It is now
        // classified into an actionable sentence, with the original one disclosure away — see
        // folderErrorCopy.js for why the cause is classified rather than assumed.
        const e = friendlyFolderError(err, sourceName)
        return (
          <div role="alert" style={{ padding: '20px 18px', display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <span style={{ fontSize: 18, lineHeight: 1 }} aria-hidden="true">⚠️</span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', marginBottom: 4 }}>
                {e.title}
              </div>
              <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.5 }}>{e.body}</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, flexWrap: 'wrap' }}>
                <button type="button" className="ghost small" onClick={() => load(current.id)}>
                  {actionLabel(e.action)}
                </button>
              </div>
              <details style={{ marginTop: 10 }}>
                <summary style={{ cursor: 'pointer', fontSize: 11.5, color: 'var(--muted)' }}>
                  Technical details
                </summary>
                {/* Kept verbatim and kept REACHABLE. Hiding it entirely would cost the support
                    conversation the only thing that identifies the failure — the point is that it
                    is not the first thing a compliance officer reads. */}
                <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                              margin: '6px 0 0', color: 'var(--muted)' }}>{err}</pre>
              </details>
            </div>
          </div>
        )
      })()}
      {!loading && !err && shown.length === 0 && (
        // "Nothing here matches your filter" and "this folder has no subfolders" are different
        // facts, and reading the first as the second is how somebody concludes a folder does not
        // exist and scans the whole Drive instead.
        <div style={{ padding: '32px 0', textAlign: 'center', color: 'var(--muted)', fontSize: 13 }}>
          {q ? `No folder in ${current.name} matches “${filter.trim()}”` : 'No subfolders here'}
        </div>
      )}
      {!loading && !err && shown.map((f, idx) => (
        <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 10,
          padding: '11px 18px', fontSize: 13,
          background: multi && !inherited && isPicked(f.id) ? '#F3EEFC' : 'transparent',
          borderBottom: idx < shown.length - 1 ? '1px solid var(--line)' : 'none' }}>
          {multi && (() => {
            // Selecting and drilling in are DIFFERENT actions on the same row, so they get
            // different targets. One control doing both is the picker bug where opening a
            // folder to look inside it silently changes what you are about to scan.
            const st = rowState(f)
            const tri = checkboxState(f, { picked, excluded, inherited, isExcluded })
            return (
              <input type="checkbox" checked={st.checked} onChange={st.onToggle}
                     // `indeterminate` has no HTML attribute — it exists only on the DOM node, so
                     // it is set through a ref callback rather than declared here.
                     ref={(el) => { if (el) el.indeterminate = tri === 'partial' }}
                     aria-checked={tri === 'partial' ? 'mixed' : undefined}
                     aria-label={inherited
                       ? `${st.checked ? 'Exclude' : 'Include'} ${f.name}`
                       : tri === 'partial'
                         ? `${f.name} — included, with a carve-out inside`
                         : `Select ${f.name}`}
                     style={{ cursor: 'pointer' }} />
            )
          })()}
          <button type="button" style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1,
            background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
            fontSize: 13, padding: 0 }}
            onClick={() => enter(f)}>
            <FolderIcon />
            <span style={{ flex: 1, color: 'var(--ink)', fontWeight: 500 }}>
              {f.name}
              {multi && inherited && (
                <span className="muted" style={{ fontSize: 11, marginLeft: 6 }}>
                  {isExcluded(f.id) ? '· excluded' : '· included via parent'}
                </span>
              )}
            </span>
            {/* Size, where the provider gives one. "items", never "files": Graph's childCount
                counts subfolders too and does not recurse, and Google Drive returns no count at
                all. A number that means a different thing per provider on the screen that decides
                what gets scanned is worse than no number. */}
            {sizeHint(f) && (
              <span className="muted" style={{ fontSize: 11.5, marginRight: 8 }}
                    title={SIZE_HINT_BASIS}>{sizeHint(f)}</span>
            )}
            <span style={{ color: 'var(--ink)', fontSize: 15 }}>›</span>
          </button>
        </div>
      ))}
    </div>
  )

  // The running selection, named. Rendered even when EMPTY, saying what empty means — "nothing
  // selected" and "everything" are the same screen otherwise, and the reassuring reading of a
  // blank picker is the wrong one.
  const chips = (
    picked.length === 0 && excluded.length === 0 ? (
      // Two opposite meanings for the same empty list, told apart by whether the CALLER claimed to
      // be narrowing. On a source card no selection is the connection's default and genuinely does
      // scan everything. In the wizard's "Specific folders" mode it is an unfinished decision, and
      // rendering "covers all of OneDrive" there authorised the whole estate in the name of a
      // restriction (#501's failed folder list is one way to arrive here without noticing).
      requireSelection ? (
        <div style={{ fontSize: 12.5, color: '#854F0B' }}>
          <strong>{INCOMPLETE_LINE}</strong>
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 12.5 }}>
          Nothing selected — this {inline ? 'scan covers' : 'source scans'} <strong>all of {rootName}</strong>.
        </div>
      )
    ) : (
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {!inline && <span className="muted" style={{ fontSize: 12.5 }}>Scanning:</span>}
        {picked.map((f) => (
          <span key={f.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
            fontSize: 12, background: '#F1EFF3', border: '1px solid var(--line)',
            borderRadius: 999, padding: '3px 8px' }}>
            📁 {f.name}
            <button type="button" className="linklike" aria-label={`Remove ${f.name}`}
                    style={{ fontSize: 13, lineHeight: 1 }}
                    onClick={() => toggle(f)}>✕</button>
          </span>
        ))}
        {/* Carve-outs are shown WITH the inclusions, not on a separate screen: "HR" and
            "HR except Archive" are different scopes, and a reader checking a count needs
            both halves in one glance. */}
        {excluded.map((f) => (
          <span key={f.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6,
            fontSize: 12, background: '#FBF0F0', border: '1px solid var(--line)',
            borderRadius: 999, padding: '3px 8px' }}>
            🚫 except {f.name}
            <button type="button" className="linklike" aria-label={`Stop excluding ${f.name}`}
                    style={{ fontSize: 13, lineHeight: 1 }}
                    onClick={() => toggleExclude(f)}>✕</button>
          </span>
        ))}
      </div>
    )
  )

  const recursionNote = (
    <div style={{ fontSize: 12.5, color: 'var(--ink)', marginBottom: 14,
                  background: '#F1EFF3', border: '1px solid var(--line)', borderRadius: 8,
                  padding: '9px 12px', display: 'flex', alignItems: 'flex-start', gap: 8,
                  lineHeight: 1.4 }}>
      <span aria-hidden="true" style={{ fontSize: 14 }}>↳</span>
      <span>Scans the chosen folder{multi ? 's' : ''} <strong>and everything inside</strong> — all subfolders, recursively{multi ? ', except any you exclude' : ''}.</span>
    </div>
  )

  // ── Inline: the browser and the scope it builds, side by side ──────────────────────────────
  // The modal makes these two sequential — pick, save, close, then read a row of chips on the
  // screen underneath — so the thing you are assembling is never visible while you assemble it,
  // and the moment it becomes visible is the moment it is too late to be cheap to change. Side by
  // side, every tick moves a chip you can already see. That is the whole reason for this layout;
  // it is not a restyle.
  if (inline) {
    return (
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        {/* 65/35. It was 2:1 on a 300px/220px basis, which lands near 62/38 once free space is
            shared out — the browser is where the work happens, so it takes the extra. Bases keep
            the wrap point sane on a narrow screen rather than letting either column collapse. */}
        <div style={{ flex: '65 1 320px', minWidth: 0 }}>
          {breadcrumb}
          {filterBox}
          {list}
        </div>
        <div style={{ flex: '35 1 240px', minWidth: 0 }} role="region" aria-label="Current scope">
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                        gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: '.04em',
                           color: 'var(--muted)' }}>CURRENT SCOPE</span>
            {(picked.length > 0 || excluded.length > 0) && (
              <button type="button" className="linklike" style={{ fontSize: 12 }}
                      onClick={clearAll}>Clear all</button>
            )}
          </div>
          <div style={{ marginBottom: 12 }}>{chips}</div>
          {recursionNote}
        </div>
      </div>
    )
  }

  return (
    <div className="setoverlay" onClick={onClose}>
      <div className="setpanel" style={{ maxWidth: 480, width: '100%', padding: '24px 28px 28px' }}
           onClick={(e) => e.stopPropagation()} role="dialog" aria-label={title}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <span style={{ fontSize: 15, fontWeight: 650, letterSpacing: '-0.01em' }}>{title}</span>
          <button className="small ghost" onClick={onClose} aria-label="Close"
                  style={{ lineHeight: 1, padding: '4px 8px', fontSize: 16, marginRight: -4 }}>✕</button>
        </div>

        {breadcrumb}
        {filterBox}
        {list}

        {multi && <div style={{ marginBottom: 14 }}>{chips}</div>}

        {recursionNote}

        {/* Footer */}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          {multi ? (
            <>
              <button className="ghost small" onClick={() => onConfirm([], [])}>Scan all of {rootName}</button>
              <button onClick={() => onConfirm(picked, excluded)}>
                {picked.length ? `Save ${picked.length} location${picked.length === 1 ? '' : 's'}` : 'Save'}
              </button>
            </>
          ) : (
            <>
              <button className="ghost small" onClick={() => onScan(null)}>Scan all of {rootName}</button>
              <button onClick={() => onScan(current.id === 'root' ? null : current.id)}>
                Scan "{current.name}" + subfolders
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
