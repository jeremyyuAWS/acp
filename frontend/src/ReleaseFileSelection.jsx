import { useMemo, useState, useRef, useEffect } from 'react'
import { releaseDestination } from './releasePolicy.js'
import { releaseReadiness, canSelectRelease } from './releaseClarityModel.js'
import './release-file-selection.css'

export function releaseFileStatus(file, done = {}, sourceState = () => undefined) {
  return releaseReadiness(file, { done, sourceState }).status
}

export function releaseFileSize(file) {
  for (const value of [file.size_bytes, file.file_size_bytes, file.size]) {
    if (Number.isFinite(Number(value)) && Number(value) >= 0) return Number(value)
  }
  return null
}

const humanBytes = (bytes) => bytes < 1024 ? `${bytes} B` : bytes < 1024 ** 2 ? `${Math.round(bytes / 1024)} KB` : bytes < 1024 ** 3 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${(bytes / 1024 ** 3).toFixed(1)} GB`

export default function ReleaseFileSelection({ files, selectedFiles, setSelectedFiles, done, sourceState, sourceProduct, releaseProvider, driveMirrorEnabled, driveMirrorFolder, releaseFolder, releaseResults, selectedFile: requestedFile, setSelectedFile, sourcePath, pending = {}, blockers = {}, allowRemainingIssues = false, destinationLabel }) {
  const selectedFile = files.find((file) => file.file === requestedFile?.file) || null
  const detailRef = useRef(null)
  const triggerRef = useRef(null)
  const openDetails = (file, event) => { triggerRef.current = event.currentTarget; setSelectedFile(file) }
  const closeDetails = () => { setSelectedFile(null); triggerRef.current?.focus() }
  useEffect(() => { if (selectedFile) detailRef.current?.focus() }, [selectedFile?.file])
  const [query, setQuery] = useState('')
  const [folder, setFolder] = useState('all')
  const [status, setStatus] = useState('all')
  const rows = useMemo(() => files.map((file) => {
    const parts = sourcePath(file).replace(/\\/g, '/').split('/')
    return { file, folder: parts.length > 1 ? parts.slice(0, -1).join('/') : 'Source root', ...releaseReadiness(file, { done, results: releaseResults, sourceState, pending, blockers, allowRemainingIssues }) }
  }), [files, done, releaseResults, sourceState, sourcePath, pending, blockers, allowRemainingIssues])
  const folders = [...new Set(rows.map((row) => row.folder))].sort((a, b) => a.localeCompare(b))
  const needle = query.trim().toLowerCase()
  const shown = rows.filter((row) => (!needle || `${row.file.file} ${row.file.sourceName || ''} ${row.file.department || ''} ${row.folder}`.toLowerCase().includes(needle)) && (folder === 'all' || row.folder === folder) && (status === 'all' || (status === 'attention' ? !['ready', 'released', 'delivering'].includes(row.status) : row.status === status)))
  const selectable = shown.filter(canSelectRelease)
  const allVisibleSelected = selectable.length > 0 && selectable.every((row) => selectedFiles.has(row.file.file))
  const counts = Object.fromEntries(['ready', 'released', 'changed', 'unreachable', 'delivering', 'attention', 'failed'].map((key) => [key, rows.filter((row) => row.status === key).length]))
  const selected = files.filter((file) => selectedFiles.has(file.file))
  const sizes = selected.map(releaseFileSize)
  const packageSize = sizes.length && sizes.every((value) => value != null) ? `Estimated package ${humanBytes(sizes.reduce((sum, value) => sum + value, 0))}` : 'Package size calculated when prepared'
  const result = selectedFile ? releaseResults[selectedFile.file] : null
  const toggleVisible = () => setSelectedFiles((old) => {
    const next = new Set(old)
    selectable.forEach(({ file }) => allVisibleSelected ? next.delete(file.file) : next.add(file.file))
    return next
  })

  return <div className="release-selection">
    <div className="release-selection__toolbar" aria-label="Filter release files">
      <label className="release-selection__search"><span className="sr-only">Search files</span><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files or folders…" /></label>
      <label><span>Folder</span><select value={folder} onChange={(event) => setFolder(event.target.value)}><option value="all">All folders ({folders.length})</option>{folders.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
      <label><span>Status</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">All statuses</option><option value="ready">Ready ({counts.ready})</option><option value="released">Delivered ({counts.released})</option><option value="attention">Needs attention ({counts.changed + counts.unreachable + counts.attention + counts.failed})</option><option value="delivering">Delivering ({counts.delivering})</option><option value="changed">Source changed ({counts.changed})</option><option value="unreachable">Source unreachable ({counts.unreachable})</option></select></label>
    </div>
    {(counts.changed > 0 || counts.unreachable > 0 || counts.released > 0) && <div className="release-selection__summary" aria-label="Release exclusions"><b>{counts.changed + counts.unreachable + counts.attention + counts.released + counts.delivering} excluded from a new source publish</b><span>{[counts.changed && `${counts.changed} source changed`, counts.unreachable && `${counts.unreachable} source unreachable — verify access`, counts.released && `${counts.released} already delivered`].filter(Boolean).join(' · ')}</span></div>}
    <div className="release-selection__layout">
      <div className="release-selection__list">
        <div className="release-selection__sticky"><label><input type="checkbox" checked={allVisibleSelected} onChange={toggleVisible} disabled={!selectable.length} /> <b>{allVisibleSelected ? 'Clear visible' : 'Select visible'}</b></label><span>{shown.length} shown · {selected.length} selected{selected.filter((file) => !shown.some((row) => row.file.file === file.file)).length > 0 && ` · ${selected.filter((file) => !shown.some((row) => row.file.file === file.file)).length} outside these filters`}</span><span>{packageSize}</span></div>
        {shown.length === 0 ? <div className="release-selection__empty"><b>No files match these filters.</b><button className="ghost small" onClick={() => { setQuery(''); setFolder('all'); setStatus('all') }}>Clear filters</button></div> : folders.filter((name) => shown.some((row) => row.folder === name)).map((name) => <section key={name} aria-label={name}>
          <h3>{name}</h3>
          {shown.filter((row) => row.folder === name).map(({ file, status: fileStatus, label, reason }) => <div className={`release-selection__row release-selection__row--${fileStatus}`} key={file.file}>
            <input type="checkbox" aria-label={`Select ${file.file}`} checked={selectedFiles.has(file.file)} disabled={!canSelectRelease({ status: fileStatus })} onChange={(event) => setSelectedFiles((old) => { const next = new Set(old); event.target.checked ? next.add(file.file) : next.delete(file.file); return next })} />
            <button className="release-selection__name" onClick={(event) => openDetails(file, event)}>{file.file}</button>
            <span className={`release-selection__status release-selection__status--${fileStatus}`}>{label}</span>
            <span className="release-selection__meta">{file.sourceName || 'Connected source'}{file.department ? ` · ${file.department}` : ''} · {file.score == null ? 'Score unknown' : `${file.score} / 100`}</span>
            <span className="release-selection__destination">{reason}</span>
            <span className="release-selection__destination">→ {destinationLabel || releaseDestination({ provider: releaseProvider, driveFileId: file.drive_file_id, driveMirrorEnabled, driveMirrorFolder }).label}</span>
            <button className="ghost small release-selection__details" onClick={(event) => openDetails(file, event)}>Details</button>
          </div>)}
        </section>)}
      </div>
      <aside hidden={!selectedFile} ref={detailRef} tabIndex={-1} onKeyDown={(event) => { if (event.key === 'Escape') { event.stopPropagation(); closeDetails() } }} className={`release-selection__drawer${selectedFile ? ' is-open' : ''}`} aria-label="Selected document release details">
        {selectedFile ? <><div className="release-selection__drawer-heading"><h3>{selectedFile.file}</h3><button className="ghost small" onClick={closeDetails} aria-label="Close file details">Close</button></div><dl><dt>Release status</dt><dd>{releaseReadiness(selectedFile, { done, results: releaseResults, sourceState, pending, blockers, allowRemainingIssues }).label}</dd><dt>Original path</dt><dd>{result?.original_relative_path || sourcePath(selectedFile)}</dd><dt>Destination path</dt><dd>{result?.released_relative_path || 'Not confirmed — review delivery for the exact path'}</dd><dt>Verification</dt><dd>{result?.verification || 'No delivery verification recorded'}</dd></dl>{result?.status === 'failed' && <div role="alert" className="release-selection__error"><b>Needs attention:</b> {result.explanation}</div>}{result?.published_url && <a href={result.published_url} target="_blank" rel="noopener noreferrer">Open released document ↗</a>}<details><summary>Audit history</summary><p className="muted">{result?.published_at ? `Released ${new Date(result.published_at).toLocaleString()} · ${result.created ? 'created' : 'reused'}` : 'No release event yet.'}</p></details></> : <p className="muted">Choose Details to inspect a file’s source, destination, verification, and audit history.</p>}
      </aside>
    </div>
  </div>
}
