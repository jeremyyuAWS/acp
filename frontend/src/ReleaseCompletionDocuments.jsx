import './release-completion-documents.css'

export default function ReleaseCompletionDocuments({ files, states, progressDocuments, results = {}, urls = {}, filter = 'all', onFilter, readOnly, publishing, onRetry, reportSummary, reportsByFile = {}, receipt }) {
  const rows = files.map((file, index) => ({ file, state: states[index], result: results[file.file] }))
  const visible = rows.filter(({ file, state }) => filter === 'all' || (progressDocuments
    ? progressDocuments.some(document => document.file === file.file && document.progressState === filter)
    : filter === 'attention' ? !['ready', 'released', 'delivering'].includes(state.status) : state.status === filter))
  return <section className="panel release-completion-documents" aria-label="Publication outcomes">
    <h3>Publication outcomes</h3>
    <p>Saved copies, verification, remaining work, and delivery receipts for this assessment.</p>
    {reportSummary}
    {receipt}
    {filter !== 'all' && <button className="ghost" onClick={() => onFilter('all')}>Show all documents</button>}
    <div className="document-findings-scroll"><table><thead><tr><th>Document</th><th>Corrected copy</th><th>Verification</th><th>Publication and remaining work</th><th>Action</th></tr></thead>
      <tbody>{visible.map(({ file, state, result }) => <tr key={file.file}>
        <th scope="row">{file.file}</th>
        <td>{file.remediated_at ? 'Saved in ACP' : 'Not saved yet'}</td>
        <td>{file.remediated_at && (file.compliant === true || file.compliant === 1) ? 'Selected checks passed' : 'Not confirmed clear'}</td>
        <td><strong>{state.label}</strong><p>{state.reason}</p>{result?.published_at && <small>Receipt recorded: {new Date(result.published_at).toLocaleString()}</small>}</td>
        <td>{state.status === 'released' && (urls[file.file] || result?.published_url) ? <a href={urls[file.file] || result.published_url} target="_blank" rel="noopener noreferrer">Open published copy</a>
          : result?.status === 'failed' && ['ready', 'failed'].includes(state.status) ? <button disabled={readOnly || publishing} onClick={() => onRetry([file.file])}>Retry delivery</button> : null}{reportsByFile[file.file]}</td>
      </tr>)}</tbody>
    </table></div>
    {!visible.length && <p>No documents in this state.</p>}
  </section>
}
