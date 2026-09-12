import { useEffect, useId, useRef, useState } from 'react'
import './progress-queue-drawer.css'

export default function ProgressQueueDrawer({ title, scopeLabel, files = [], loading = false, error, onClose, onOpenFile }) {
  const id = useId()
  const panel = useRef(null)
  const close = useRef(onClose)
  close.current = onClose
  const [query, setQuery] = useState('')
  useEffect(() => setQuery(''), [title])
  useEffect(() => {
    const opener = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    panel.current?.querySelector('button')?.focus()
    return () => { document.body.style.overflow = previousOverflow; if (opener?.isConnected) opener.focus() }
  }, [])
  const visible = files.filter(row => `${row.file || ''} ${row.label || row.status || ''} ${row.reason || ''}`.toLowerCase().includes(query.trim().toLowerCase()))
  function keyboard(event) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close.current?.(); return }
    if (event.key !== 'Tab') return
    const targets = [...panel.current.querySelectorAll('button:not(:disabled),input:not(:disabled),a[href],[tabindex="0"]')]
    const first = targets[0], last = targets.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }
  return <div className="progress-queue-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose?.() }}>
    <aside ref={panel} className="progress-queue-drawer" role="dialog" aria-modal="true" aria-labelledby={id} onKeyDown={keyboard}>
      <header><div><h2 id={id}>{title}</h2><p>{scopeLabel || 'Current assessment'}</p></div><button type="button" className="ghost" aria-label="Close queue" onClick={onClose}>Close</button></header>
      <label className="progress-queue-search">Search files<input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search by file name or status"/></label>
      <p className="progress-queue-count" role="status">{!files.length && error ? 'File count unavailable' : !files.length && loading ? 'Loading file queue…' : `${visible.length} of ${files.length} file${files.length === 1 ? '' : 's'} shown`}</p>
      {loading && <p role="status">Updating saved queue…</p>}
      {error && <p className="progress-queue-error" role="alert">{typeof error === 'string' ? error : 'This queue could not refresh. Try opening it again.'}</p>}
      <div className="progress-queue-list" tabIndex={0} aria-label="Queue files">
        {visible.map((row, index) => <article key={row.id || `${row.file}-${index}`} className="progress-queue-file"><div className="progress-queue-file-heading"><strong>{row.file}</strong><span className={`progress-queue-status queue-${row.status || 'unknown'}`}>{row.label || row.status || 'Awaiting confirmed status'}</span></div>
          {row.reason && <p>{row.reason}</p>}
          {Number.isInteger(row.findingCount) && row.findingCount >= 0 && <small>{row.findingCount} finding{row.findingCount === 1 ? '' : 's'}</small>}
          {row.href && <a href={row.href}>Open file</a>}
          {onOpenFile && row.status !== 'blocked' && <button type="button" className="ghost small" onClick={() => onOpenFile(row)}>View file details</button>}
        </article>)}
        {!visible.length && !loading && !error && <p className="progress-queue-empty">{query.trim() ? 'No files match your search.' : 'No files are currently in this queue.'}</p>}
      </div>
      <footer>Counts and statuses update from saved results. Processed does not mean fully remediated.</footer>
    </aside>
  </div>
}
