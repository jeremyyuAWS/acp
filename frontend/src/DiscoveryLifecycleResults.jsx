import { useEffect, useState } from 'react'
import { getLifecycleRuleResults, getLifecycleSummary, listDispositionPolicies } from './api.js'
import { LIFECYCLE_ACTIONS } from './lifecycleRules.js'
import { formatBucketOf } from './discoveryRecommendations.js'
import LifecycleEstateSummary from './LifecycleEstateSummary.jsx'
import LifecycleRuleLedger from './LifecycleRuleLedger.jsx'

const FORMATS = new Set(['pdf', 'docx', 'xlsx', 'pptx'])
const NATIVE = { 'application/vnd.google-apps.document': 'docx', 'application/vnd.google-apps.spreadsheet': 'xlsx', 'application/vnd.google-apps.presentation': 'pptx' }
export const supportedDiscoveryRow = row => FORMATS.has(NATIVE[row.mime] || formatBucketOf(row))
const showDate = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : 'Not recorded'

export default function DiscoveryLifecycleResults({ rows, policies, scanId, source = null }) {
  const [rule, setRule] = useState('all')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  useEffect(() => { setPage(0) }, [rule, search, rows])
  const [loaded, setLoaded] = useState(null)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState(null)
  const [ruleResults, setRuleResults] = useState([])
  const [lifecycleError, setLifecycleError] = useState('')
  // The embedded workspace is a REVIEW queue, not a second copy of the inventory below it.
  // Start on actionable lifecycle candidates; an explicit estate-segment click may broaden it.
  useEffect(() => {
    let current = true
    setSummary(null); setRuleResults([]); setLifecycleError('')
    if (!scanId) return () => { current = false }
    Promise.all([getLifecycleSummary(scanId), getLifecycleRuleResults(scanId)]).then(([s, ledger]) => {
      if (current) { setSummary(s); setRuleResults(ledger.rules || []) }
    }).catch(() => { if (current) setLifecycleError('The durable lifecycle snapshot could not be loaded. Inventory results remain available below.') })
    return () => { current = false }
  }, [scanId])
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
  const lastPage = Math.max(0, Math.ceil(shown.length / 50) - 1)
  const currentPage = Math.min(page, lastPage)
  const visible = shown.slice(currentPage * 50, (currentPage + 1) * 50)
  return <section className="panel" aria-label="Lifecycle results for supported documents">
    {lifecycleError && <p role="alert">{lifecycleError}</p>}
    {summary && <LifecycleEstateSummary summary={summary}
      onRules={() => document.getElementById('lifecycle-rules')?.scrollIntoView()} />}
    {summary && <div id="lifecycle-rules"><LifecycleRuleLedger rules={ruleResults} integrity={summary.integrity} /></div>}
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
    <p role="status">{shown.length} of {supported.length} supported documents match. Showing {shown.length ? currentPage * 50 + 1 : 0}–{Math.min((currentPage + 1) * 50, shown.length)}. Counts reflect the recorded winning rule, not every rule that could match.</p>
    {shown.length === 0 && <p>No supported documents match these filters.</p>}
    <div style={{ maxHeight: 420, overflow: 'auto' }}>
      {visible.map(r => <details key={r.file} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
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
    {shown.length > 50 && <nav aria-label="Lifecycle result pages" style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 12 }}>
      <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous page</button>
      <span>Page {currentPage + 1} of {lastPage + 1}</span>
      <button type="button" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next page</button>
    </nav>}
    <p className="muted">Archive and deletion candidates are recommendations. No source files are moved or deleted by this view.</p>
  </section>
}
