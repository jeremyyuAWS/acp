import { useEffect, useState } from 'react'
import { listDispositionPolicies } from './api.js'
import { LIFECYCLE_ACTIONS } from './lifecycleRules.js'
import { formatBucketOf } from './discoveryRecommendations.js'

const FORMATS = new Set(['pdf', 'docx', 'xlsx', 'pptx'])
const NATIVE = { 'application/vnd.google-apps.document': 'docx', 'application/vnd.google-apps.spreadsheet': 'xlsx', 'application/vnd.google-apps.presentation': 'pptx' }
export const supportedDiscoveryRow = row => FORMATS.has(NATIVE[row.mime] || formatBucketOf(row))
const showDate = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : 'Not recorded'

export default function DiscoveryLifecycleResults({ rows, policies, scanId }) {
  const [rule, setRule] = useState('all')
  const [search, setSearch] = useState('')
  const [loaded, setLoaded] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let current = true
    setLoaded(null); setError(''); setRule('all')
    if (policies == null && scanId) listDispositionPolicies().then(value => {
      if (current) setLoaded(value)
    }).catch(() => { if (current) setError('Rule names could not be loaded. Saved file results are still shown.') })
    return () => { current = false }
  }, [policies, scanId])
  policies = policies ?? loaded
  if (!Array.isArray(rows)) return null
  const supported = rows.filter(supportedDiscoveryRow)
  const rules = (Array.isArray(policies) ? policies : []).filter(p => p.enabled && LIFECYCLE_ACTIONS.has(p.action))
  const names = new Map((Array.isArray(policies) ? policies : []).map(p => [String(p.policy_id), p.name]))
  const shown = supported.filter(r => (rule === 'all' || String(r.lifecycle_rule_id) === rule) && String(r.file || '').toLowerCase().includes(search.toLowerCase()))
  return <section className="panel" aria-label="Lifecycle results for supported documents">
    <h2>Lifecycle results · supported documents</h2>
    <p className="muted">PDF, Word (DOCX), Excel (XLSX), PowerPoint (PPTX), including their Google equivalents. Results are saved from this scan; changing a rule requires a new scan.</p>
    {error && <p role="alert">{error}</p>}
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
      <label>Lifecycle rule <select value={rule} onChange={e => setRule(e.target.value)}>
        <option value="all">All supported documents ({supported.length})</option>
        {rules.map(p => <option key={p.policy_id} value={String(p.policy_id)}>{p.name || 'Unnamed rule'} ({supported.filter(r => String(r.lifecycle_rule_id) === String(p.policy_id)).length})</option>)}
      </select></label>
      <label>Find a document <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search file names" /></label>
      <button type="button" onClick={() => { setRule('all'); setSearch('') }}>Clear filters</button>
    </div>
    <p role="status">{shown.length} of {supported.length} supported documents shown. Counts reflect the recorded winning rule, not every rule that could match.</p>
    {shown.length === 0 && <p>No supported documents match these filters.</p>}
    <div style={{ maxHeight: 420, overflow: 'auto' }}>
      {shown.map(r => <details key={r.file} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
        <summary>{r.file} · {r.lifecycle_status || 'Lifecycle status not recorded'}</summary>
        <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(100px, 150px) 1fr', gap: 8, overflowWrap: 'anywhere' }}>
          <dt>Matched rule</dt><dd>{r.lifecycle_rule_id ? names.get(String(r.lifecycle_rule_id)) || `Recorded rule ${r.lifecycle_rule_id}` : 'No matched rule recorded'}</dd>
          <dt>Reason</dt><dd>{r.lifecycle_reason || 'Not recorded'}</dd>
          <dt>Last modified</dt><dd>{showDate(r.source_modified)}</dd>
          <dt>Created</dt><dd>{showDate(r.created_at)}</dd>
          <dt>Owner</dt><dd>{r.owner || 'Not recorded'}</dd>
          <dt>Size</dt><dd>{r.size_kb != null ? `${Number(r.size_kb).toLocaleString()} KB` : 'Not recorded'}</dd>
          <dt>Source path</dt><dd>{r.path || 'Not recorded'}</dd>
        </dl>
      </details>)}
    </div>
    <p className="muted">Archive and deletion candidates are recommendations. No source files are moved or deleted by this view.</p>
  </section>
}
