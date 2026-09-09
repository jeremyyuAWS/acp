import { useMemo, useState } from 'react'
import { rowName, rowPath, searchRows } from './bucketMembers.js'

// The list behind a breakdown bar: click "Other", see which files are in it.
//
// Three things it refuses to do, because this screen's whole job is to be checkable:
//
//   · It never shows a short list silently. When the caller hands it fewer rows than the bar
//     claims — which happens on BY FILE TYPE, whose counts come from the server's whole-estate
//     summary while the browser only holds the rows the inventory route returned — it says so, in
//     the panel, with both numbers. A list that quietly under-reports is worse than no list.
//   · It never reports a filtered count as the bucket's count. The header always shows
//     "showing N of M" while a search is active, so a reader cannot mistake their own filter for
//     the estate.
//   · It is operable without a mouse. The trigger is a real <button> with aria-expanded and
//     aria-controls; the list is a plain <ul>. Shipping a keyboard trap inside an accessibility
//     product is the one bug this repo cannot ship.
//
// SEARCH IS CLIENT-SIDE over rows already in memory — the caller has them, this does no fetching.

/** Above this many rows the list gets a search box; below it, searching is just clutter. */
export const SEARCH_THRESHOLD = 8

/** Rows past this are not rendered at all — see the note on `VISIBLE_CAP` below. */
export const VISIBLE_CAP = 500

export default function BucketFiles({ id, bucket, rows = [], onClose = null }) {
  const [query, setQuery] = useState('')
  const all = Array.isArray(rows) ? rows : []
  const matched = useMemo(() => searchRows(all, query), [all, query])
  const shown = matched.slice(0, VISIBLE_CAP)

  // The bar's number and the rows we actually hold. Equal in every case but the estate-inventory
  // one; when they differ the caller has NOT made a mistake, so this explains rather than warns.
  const claimed = Number(bucket?.count)
  const short = Number.isFinite(claimed) && claimed > all.length

  return (
    <div id={id} className="panel" style={{ margin: '2px 0 10px', padding: '10px 12px',
                                            background: 'var(--bg-subtle, rgba(0,0,0,0.02))' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                    gap: 12, flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 13 }}>{bucket?.label}</strong>
        <span className="muted" style={{ fontSize: 12 }} role="status">
          {query.trim()
            ? `showing ${shown.length.toLocaleString()} of ${all.length.toLocaleString()}`
            : `${all.length.toLocaleString()} ${all.length === 1 ? 'file' : 'files'}`}
        </span>
      </div>

      {short && (
        <p className="muted" style={{ fontSize: 11.5, margin: '6px 0 0', lineHeight: 1.5 }}>
          Listing the {all.length.toLocaleString()} of {claimed.toLocaleString()} this screen read
          per file. The bar counts the whole estate listing, which is summarised on the server —
          the rest were counted there and never read row by row here.
        </p>
      )}

      {all.length > SEARCH_THRESHOLD && (
        <label style={{ display: 'block', margin: '8px 0 0' }}>
          <span className="sr-only">Search files in {bucket?.label}</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name or path"
            style={{ width: '100%', boxSizing: 'border-box', fontSize: 12.5, padding: '5px 8px' }}
          />
        </label>
      )}

      {shown.length === 0 ? (
        <p className="muted" style={{ fontSize: 12.5, margin: '8px 0 0' }}>
          {all.length === 0 ? 'No files were read for this bucket.' : 'No file matches that search.'}
        </p>
      ) : (
        // A fixed max-height with its own scrollbar, so a 40,000-file bucket does not push the rest
        // of the screen off the page. tabIndex makes the region focusable, which is what lets a
        // keyboard user scroll it at all — a scroll container that only a mouse can reach is a
        // barrier, not a feature.
        <ul
          tabIndex={0}
          aria-label={`Files in ${bucket?.label}`}
          style={{ maxHeight: 260, overflowY: 'auto', margin: '8px 0 0', padding: '0 0 0 18px',
                   fontSize: 12.5, lineHeight: 1.7 }}
        >
          {shown.map((row, i) => {
            const path = rowPath(row)
            return (
              <li key={`${rowName(row)}-${i}`}>
                {rowName(row)}
                {path && <span className="muted" style={{ fontSize: 11.5 }}> · {path}</span>}
              </li>
            )
          })}
        </ul>
      )}

      {/* Rendering 40,000 <li>s costs more than it tells anyone. The cap is stated rather than
          silent, and the search box above narrows to what the reader is actually looking for. */}
      {matched.length > VISIBLE_CAP && (
        <p className="muted" style={{ fontSize: 11.5, margin: '6px 0 0' }}>
          First {VISIBLE_CAP.toLocaleString()} shown of {matched.length.toLocaleString()} matching.
          Search to narrow the list.
        </p>
      )}

      {onClose && (
        <button type="button" onClick={onClose} className="linklike"
                style={{ marginTop: 8, fontSize: 12 }}>
          Close
        </button>
      )}
    </div>
  )
}
