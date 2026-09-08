import RemediationFileItems from './RemediationFileItems.jsx'
import useForecastDeltas from './useForecastDeltas.js'
import Drawer from './Drawer.jsx'
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { getRemediationImpact, saveRemediationImpactPolicy, assignRemediationImpact } from './api.js'
import './remediation-impact-card.css'
import RemediationPlanChoices from './RemediationPlanChoices.jsx'

const RULE_STOPS = [
  ['Review first', 'Ask a person to approve rule-based proposals before application.'],
  ['Verified fixes', 'Permit eligible rule-based proposals with qualifying validation evidence.'],
  ['Eligible fixes', 'Also permit supported rule-based proposals with the required evidence. Verify after application.'],
]
const AI_STOPS = [
  ['Off', 'Generate no new AI proposals and apply no AI proposals in this planned run. Existing proposals remain in history.'],
  ['Draft for review', 'Generate supported AI drafts. A person must approve them before application.'],
  ['Validated drafts', 'Also permit eligible, validated, non-subjective AI proposals without approval.'],
  ['Eligible drafts', 'Also permit supported AI proposals that meet the execution service’s eligibility requirements.'],
]
const LANES = [['automatic', 'Apply automatically'], ['review', 'Review a proposal'], ['manual', 'Manual work'], ['blocked', 'Blocked / unknown']]
const OUTLOOKS = [['could_complete', 'Could complete automatically'], ['human_work', 'Human work remains'], ['blocked_incomplete', 'Blocked / assessment incomplete'], ['unavailable', 'Forecast unavailable']]
const number = value => Number.isFinite(value) ? value.toLocaleString() : 'Not yet available'
const delta = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toLocaleString()}` : 'Not yet available'
const validPolicy = p => Number.isInteger(p?.rule_based) && p.rule_based >= 0 && p.rule_based <= 2 && Number.isInteger(p?.ai) && p.ai >= 0 && p.ai <= 3
const validBudget = p => p?.ai_budget_usd === undefined || (/^\d{1,7}(?:\.\d{1,2})?$/.test(p.ai_budget_usd) && Number(p.ai_budget_usd) <= 1000000)
const policyName = p => validPolicy(p) ? `${RULE_STOPS[p.rule_based][0]} · AI: ${AI_STOPS[p.ai][0]}` : 'Not yet available'
const reasonText = reason => typeof reason === 'string' ? reason.replaceAll('_', ' ') : 'Reason not available'
const fileType = file => {
  const match = String(file || '').trim().match(/\.([^.\/]+)$/)
  return match ? match[1].toLowerCase() : 'other'
}

function PolicySlider({ title, question, stops, value, onChange, disabled, maxLevel = stops.length - 1 }) {
  const id = useId()
  return <div className="remediation-impact__control">
    <h3>{title}</h3>
    <label htmlFor={id}>{question}</label>
    <input id={id} type="range" min="0" max={maxLevel} step="1" value={value}
      disabled={disabled} onChange={event => onChange(Number(event.target.value))}
      aria-valuetext={`${stops[value][0]}: ${stops[value][1]}`} aria-describedby={`${id}-description`} />
    <div className="remediation-impact__stops" style={{ gridTemplateColumns: `repeat(${(maxLevel + 1)}, minmax(0, 1fr))` }}>
      {stops.slice(0, maxLevel + 1).map(([label], index) => <button key={label} type="button" disabled={disabled || index > maxLevel}
        aria-pressed={value === index} onClick={() => onChange(index)}>{label}</button>)}
    </div>
    {maxLevel < stops.length - 1 && <p className="remediation-impact__unavailable">Unavailable: {stops.slice(maxLevel + 1).map(([label]) => label).join(' · ')}</p>}
    <p id={`${id}-description`} className="remediation-impact__description">{stops[value][1]}</p>
  </div>
}

export default function RemediationImpactCard({ runId, onRun, runBusy = false, myEmail = '', readOnly = false, refreshKey = 0, scopeFiles, renderAssessment }) {
  const titleId = useId()
  const assigneeId = useId()
  const [assignmentOpen, setAssignmentOpen] = useState(false)
  const [assignmentFiles, setAssignmentFiles] = useState([])
  const [assignee, setAssignee] = useState(myEmail)
  const [assigning, setAssigning] = useState(false)
  const [assignmentResult, setAssignmentResult] = useState(null)
  const [assignmentError, setAssignmentError] = useState('')
  const scopeKey = Array.isArray(scopeFiles) ? JSON.stringify([...scopeFiles].sort()) : null
  const [selectedFile, setSelectedFile] = useState(null)
  const fileTrigger = useRef(null)
  useEffect(() => {
    if (!selectedFile && fileTrigger.current?.isConnected) {
      fileTrigger.current.focus()
      fileTrigger.current = null
    }
  }, [selectedFile])
  const [draft, setDraft] = useState(null)
  const policy = draft?.runId === runId ? draft.policy : null
  const setPolicy = value => setDraft(current => ({ runId, policy: typeof value === 'function' ? value(current?.runId === runId ? current.policy : null) : value }))
  const [reload, setReload] = useState(0)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)
  const [filter, setFilter] = useState(null)
  const closeDetails = useCallback(() => setFilter(null), [])
  const [fileSearch, setFileSearch] = useState('')
  const [fileTypeFilter, setFileTypeFilter] = useState('all')
  useEffect(() => { setSelectedFile(null); setAssignmentOpen(false); setAssignmentResult(null); setAssignmentError(''); setFileSearch(''); setFileTypeFilter('all') }, [filter, scopeKey, runId])
  const sequence = useRef(0)
  const runRef = useRef(runId)
  // A run switch must not submit the previous run's edited policy.
  useEffect(() => { runRef.current = runId; setData(null); setFilter(null); setNotice('') }, [runId])
  useEffect(() => {
    const request = ++sequence.current
    let cancelled = false
    if (!runId) { setLoading(false); return }
    setLoading(true); setError('')
    const requestedPolicy = runRef.current === runId ? policy : null
    if (!validBudget(requestedPolicy)) {
      setLoading(false); setError('Enter an AI spending limit from $0 to $1,000,000 with at most two decimal places.')
      return
    }
    Promise.resolve().then(() => getRemediationImpact(runId, requestedPolicy, scopeKey === null ? undefined : JSON.parse(scopeKey))).then(result => {
      if (cancelled || request !== sequence.current) return
      setData(result)
    }).catch(err => { if (!cancelled && request === sequence.current) { setError(err?.message || 'The preview could not be loaded.') } })
      .finally(() => { if (!cancelled && request === sequence.current) setLoading(false) })
    return () => { cancelled = true }
  }, [runId, policy, refreshKey, reload, scopeKey])

  const basePolicy = policy || (validPolicy(data?.policy) ? data.policy : { rule_based: 0, ai: 0 })
  const selected = data?.capabilities?.ai_budget === true ? { ai_budget_usd: '0.00', ...basePolicy } : basePolicy
  const ready = !!data && !loading && !error && data.integrity?.complete === true
  const countDeltas = useForecastDeltas({
    identity: JSON.stringify([runId, scopeKey]), ready,
    policyKey: `${data?.policy?.rule_based}:${data?.policy?.ai}`,
    automatic: data?.lanes?.automatic?.findings,
    human: Number.isFinite(data?.lanes?.review?.findings) && Number.isFinite(data?.lanes?.manual?.findings)
      ? data.lanes.review.findings + data.lanes.manual.findings : undefined,
  })
  const change = (key, value) => { setNotice(''); setFilter(null); setPolicy(current => ({ ...(current || selected), [key]: value })) }
  const categoryFiles = (data?.files || []).filter(file => !filter || filter.type === 'all' || (filter.type === 'human' ? file.review > 0 || file.manual > 0 : filter.type === 'outlook' ? file.outlook === filter.key : file[filter.key] > 0))
  const fileTypes = [...new Set(categoryFiles.map(file => fileType(file.file)))].sort()
  const searchText = fileSearch.trim().toLowerCase()
  const filteredFiles = categoryFiles.filter(file =>
    (!searchText || String(file.file || '').toLowerCase().includes(searchText)) &&
    (fileTypeFilter === 'all' || fileType(file.file) === fileTypeFilter))
  const reasons = Object.values((data?.findings || []).filter(row => row.lane !== 'automatic').reduce((groups, row) => {
    const key = row.primary_reason || 'reason_unavailable'
    const group = groups[key] ||= { reason: key, findings: 0, files: new Set() }
    group.findings += Number.isFinite(row.finding_count) ? row.finding_count : 1
    if (row.file) group.files.add(row.file)
    return groups
  }, {}))
  const humanFiles = filteredFiles.filter(file => file.review > 0 || file.manual > 0 || file.blocked > 0)
  async function assign(event) {
    event.preventDefault()
    if (readOnly || assigning || !assignmentFiles.length || data?.capabilities?.assign !== true) return
    const assignmentRun = runId
    setAssigning(true); setAssignmentError(''); setAssignmentResult(null)
    try {
      const result = await assignRemediationImpact(runId, assignmentFiles, assignee.trim(), selected)
      if (runRef.current !== assignmentRun) return
      setAssignmentResult(result)
    } catch (err) {
      if (runRef.current === assignmentRun) setAssignmentError(err?.message || 'Assignment failed. Please try again.')
    } finally { setAssigning(false) }
  }
  async function save() {
    setSaving(true); setNotice('')
    const savingRun = runId
    try {
      const saved = await saveRemediationImpactPolicy(runId, selected, data?.active_policy?.revision)
      if (runRef.current !== savingRun) return
      if (saved?.policy) setData(current => ({ ...current, active_policy: saved.policy }))
      setReload(current => current + 1)
      setNotice('Saved as the default for future runs. This run has not changed.')
    }
    catch (err) { setNotice(`Could not save defaults: ${err?.message || 'Please try again.'}`) }
    finally { setSaving(false) }
  }

  return <section id="remediation-plan" tabIndex={-1} className="remediation-impact" aria-labelledby={titleId} aria-busy={loading}>
    <header className="remediation-impact__header"><div><span className="remediation-impact__eyebrow">{scopeKey === null ? 'Remediation planner' : 'Selected remediation scope'} · Preview only</span>
      <h2 id={titleId}>Choose your remediation plan</h2>
      <p>{ready ? <><strong>{number(data.open?.findings)} unresolved findings</strong> across <strong>{number(data.open?.files)} files</strong>.</> : 'Preview the current assessment before applying changes.'}</p>
    </div><div className="remediation-impact__active"><span>Active settings</span><strong>{policyName(data?.active_policy)}</strong></div></header>
    <div className="remediation-impact__split"><div className="remediation-impact__settings">
    <RemediationPlanChoices policy={selected} providers={data?.providers}
      disabled={!runId || runBusy} onChange={change} budgetSupported={data?.capabilities?.ai_budget === true} />
    <details className="remediation-impact__advanced"><summary>Advanced: individual fix permissions</summary>
    <div className="remediation-impact__controls">
      <PolicySlider title="Rule-based fixes" question="What rule-based fixes may ACP apply without approval?" stops={RULE_STOPS}
        value={selected.rule_based} onChange={value => change('rule_based', value)} disabled={!validPolicy(data?.policy) || runBusy} />
      <PolicySlider title="AI-assisted fixes" question="What may ACP do with AI proposals?" stops={AI_STOPS}
        value={selected.ai} onChange={value => change('ai', value)} disabled={!validPolicy(data?.policy) || runBusy} maxLevel={data?.capabilities?.ai_automatic === true ? 3 : 1} />
    </div>
    {data?.capabilities?.ai_automatic !== true && <p className="remediation-impact__note">{data?.capabilities?.ai_automatic_reason || 'Automatic application of AI proposals is not available on this execution path. Drafting depends on AI settings and a usable connection.'}</p>}
    </details>
    <p className="remediation-impact__guard">These controls change remediation permissions, not assessment results or provider credentials. Human-only and subjective decisions stay protected.</p>
    <details className="remediation-impact__providers"><summary>AI connections and model details</summary>
      {data?.providers && <ul>{[['text', 'Text drafting'], ['vision', 'Image drafting']].map(([key, label]) =>
        <li key={key}>{label}: {data.providers[key]?.provider || 'Not yet available'}
          {' · '}{data.providers[key]?.model || 'Model not reported'}{' · Connection not tested'}</li>)}</ul>}
      <p>Connections are not tested by this preview. Configured credentials alone do not establish a working connection.</p>
      <p>Text and image drafting use their separately configured providers. A drafting opportunity is not a guaranteed resolution.</p>
      {data?.capabilities?.reason && <p>{data.capabilities.reason}</p>}
    </details>
    </div><div className="remediation-impact__results">
    {renderAssessment?.({
      automaticDelta: countDeltas?.automatic, humanDelta: countDeltas?.human,
      automatic: ready ? number(data.lanes?.automatic?.findings) : 'Not yet available',
      human: ready && Number.isFinite(data.lanes?.review?.findings) && Number.isFinite(data.lanes?.manual?.findings)
        ? number(data.lanes.review.findings + data.lanes.manual.findings) : 'Not yet available',
      onAutomatic: ready ? () => setFilter({ type: 'lane', key: 'automatic', label: 'Auto-fix available' }) : undefined,
      onHuman: ready ? () => setFilter({ type: 'human', label: 'Human review required' }) : undefined,
    })}
    <div role="status" aria-live="polite" aria-atomic="true" className="remediation-impact__status">
      {loading ? 'Calculating the impact of these settings…' : error ? `Preview unavailable. ${error}` : !runId ? 'Select an assessment to preview remediation.' : !ready ? 'The preview could not be reconciled. Counts are unavailable.' : `${number(data.lanes?.automatic?.findings)} findings eligible for automatic application. ${number(data.lanes?.review?.findings)} findings require proposal review.`}
      {notice && <span> {notice}</span>}
    </div>
    {data?.ai_spending && <section aria-label="AI spending for the latest remediation run">
      <h3>AI spending · Latest remediation run</h3>
      <p>{[['Spent', 'spent_units'], ['Reserved for requests', 'held_units'], ['Remaining', 'available_units'], ['Limit', 'cap_units']].map(([label, key]) =>
        <span key={key}>{label}: {Number.isSafeInteger(data.ai_spending[key]) ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(data.ai_spending[key] / 1000000) : 'Unavailable'}{' · '}</span>)}</p>
      <p>{data.ai_spending.blocked ? 'AI is paused while an uncertain charge or spending overrun is reconciled.' : 'Reservations cover requests that may still be charged. Infrastructure costs are separate.'}</p>
    </section>}
    {ready && <>
      <h3>How the findings will be handled</h3>
      <div className="remediation-impact__routes">{LANES.map(([key, label]) => <button type="button" key={key}
        className={`remediation-impact__route--${key}`} onClick={() => setFilter({ type: 'lane', key, label })}>
        <span>{label}</span><strong>{number(data.lanes?.[key]?.findings)}</strong>
        <span>{({ automatic: 'Eligible fixes without approval', review: 'A person approves a proposed fix', manual: 'Content edits or accessibility judgments', blocked: 'Investigate before remediation' })[key]}</span>
        <span className="remediation-impact__route-link">View findings →</span>
      </button>)}</div>
      <details className="remediation-impact__comparison"><summary>Compare with active settings</summary>
      <div className="remediation-impact__table-wrap"><table><caption className="sr-only">Finding routes for active and preview settings</caption>
        <thead><tr><th scope="col">Finding route</th><th scope="col">Active findings</th><th scope="col">Preview findings</th><th scope="col">Change</th><th scope="col">Affected files</th></tr></thead>
        <tbody>{LANES.map(([key, label]) => <tr key={key} className={`remediation-impact__lane--${key}`}>
          <th scope="row"><button type="button" onClick={() => setFilter({ type: 'lane', key, label })}>{label}</button></th>
          <td>{number(data.active_lanes?.[key]?.findings)}</td><td><strong>{number(data.lanes?.[key]?.findings)}</strong></td>
          <td>{delta(data.lanes?.[key]?.delta)}</td><td>{number(data.lanes?.[key]?.files)}</td>
        </tr>)}</tbody></table></div></details>
      <p className="remediation-impact__note">Affected-file counts overlap: one file may contain automatic fixes and human work. Finding routes do not overlap.</p>
      <h3>Document outlook</h3><div className="remediation-impact__outlooks">{OUTLOOKS.map(([key, label]) => <button type="button" key={key}
        onClick={() => setFilter({ type: 'outlook', key, label })}><strong>{number(data.file_outlook?.[key]?.files)}</strong><span>{label}</span></button>)}</div>
      <p className="remediation-impact__note">Each file appears in one outlook. Completion is conditional on fixes passing verification and required assessment checks being complete.</p>
      <details className="remediation-impact__remaining"><summary>Why human work remains</summary>
        <ul>{reasons.length ? reasons.map(group => <li key={group.reason}>{reasonText(group.reason)} — {number(group.findings)} findings across {number(group.files.size)} files</li>) : <li>No remaining-work reasons were returned.</li>}</ul>
        <p>Review proposals, edit source content, resolve accessibility judgments, or investigate blockers. Assignment does not resolve findings.</p>
      </details>
      <button type="button" onClick={() => setFilter({ type: 'all', label: 'All affected files' })}>Inspect affected files</button>
      {filter && <Drawer title={selectedFile || filter.label} subtitle="Projected work for the selected scope and settings" onClose={closeDetails}>
        <div className="remediation-impact__drilldown">
        <div hidden={!!selectedFile}>
        <p>{filter.type === 'human' ? 'This includes proposals needing approval and manual work. AI suggestions require approval; accessibility judgments need a person.' : filter.key === 'automatic' ? 'These findings are eligible for automatic application under this plan. They are not fixed yet; completion depends on verification.' : 'Inspect the affected files and select a filename to see reasons and next actions.'}</p>
        <button type="button" onClick={closeDetails}>Close details</button>
        <div className="remediation-impact__file-filters" role="search" aria-label="Filter affected files">
          <label>Search by name
            <input type="search" value={fileSearch} placeholder="Search files…"
              onChange={event => setFileSearch(event.target.value)} />
          </label>
          <label>File type
            <select value={fileTypeFilter} onChange={event => setFileTypeFilter(event.target.value)}>
              <option value="all">All file types</option>
              {fileTypes.map(type => <option key={type} value={type}>{type === 'other' ? 'Other' : type.toUpperCase()}</option>)}
            </select>
          </label>
          <span className="remediation-impact__file-count" role="status" aria-live="polite">
            {number(filteredFiles.length)} of {number(categoryFiles.length)} files
          </span>
          {(fileSearch || fileTypeFilter !== 'all') && <button type="button" onClick={() => { setFileSearch(''); setFileTypeFilter('all') }}>Clear filters</button>}
        </div>
        {filteredFiles.length ? <div className="remediation-impact__table-wrap"><table><caption>Files in this preview category</caption>
          <thead><tr><th>File</th><th>Open findings</th><th>Automatic</th><th>Review</th><th>Manual</th><th>Blocked</th></tr></thead>
          <tbody>{filteredFiles.map((file, index) => <tr key={`${file.file}-${index}`}><th scope="row"><button type="button" onClick={event => { fileTrigger.current = event.currentTarget; setSelectedFile(file.file) }}>{file.file || 'Unnamed file'}</button></th>
            <td>{number(file.findings)}</td><td>{number(file.automatic)}</td><td>{number(file.review)}</td><td>{number(file.manual)}</td><td>{number(file.blocked)}</td></tr>)}</tbody>
        </table></div> : <p>No files match these filters.</p>}

        <button type="button" disabled={readOnly || assigning || !humanFiles.length || data?.capabilities?.assign !== true}
          onClick={() => { setAssignmentFiles(humanFiles.map(file => file.file)); setAssignee(myEmail); setAssignmentOpen(true); setAssignmentResult(null); setAssignmentError('') }}>Assign human work</button>
        {data?.capabilities?.assign !== true && <p>Assignment is not available for this preview.</p>}
        {assignmentOpen && <form className="remediation-impact__assignment" onSubmit={assign}>
          <h4>Assign remaining human work</h4>
          <fieldset disabled={assigning || readOnly}><legend>Select files</legend>
            {humanFiles.map(file => <label key={file.file}><input type="checkbox" checked={assignmentFiles.includes(file.file)}
              onChange={event => setAssignmentFiles(current => event.target.checked ? [...current, file.file] : current.filter(name => name !== file.file))} /> {file.file}</label>)}
          </fieldset>
          <label htmlFor={assigneeId}>Assignee email</label>
          <input id={assigneeId} type="email" required value={assignee} disabled={assigning || readOnly} onChange={event => setAssignee(event.target.value)} />
          <p>This assigns pending review work. Approved work and work already in review may be skipped. No findings are marked resolved.</p>
          <button type="submit" disabled={assigning || readOnly || !assignmentFiles.length || !assignee.trim()}>{assigning ? 'Assigning…' : 'Confirm assignment'}</button>
          <button type="button" disabled={assigning} onClick={() => setAssignmentOpen(false)}>Cancel assignment</button>
          {assignmentError && <p role="alert">Could not assign work: {assignmentError}</p>}
          {assignmentResult && <div role="status"><p>{number(assignmentResult.tasks_assigned)} tasks covering {number(assignmentResult.findings_assigned)} findings across {number(assignmentResult.files_assigned)} files assigned to {assignmentResult.assignee || assignee}.</p>
            <ul>{(assignmentResult.results || []).map((result, index) => <li key={`${result.file}-${index}`}>{result.file}: {result.status}{result.message ? ` — ${result.message}` : ''}</li>)}</ul>
          </div>}
        </form>}
        </div>
        {selectedFile && <RemediationFileItems key={selectedFile}
          file={(data.files || []).find(file => file.file === selectedFile) || { file: selectedFile }}
          rows={data.findings || []}
          initialLane={(data.files || []).find(file => file.file === selectedFile)?.manual > 0 ? 'manual' : filter.type === 'lane' ? filter.key : 'review'}
          onBack={() => setSelectedFile(null)} />}
      </div></Drawer>}
    </>}
    </div></div>
    {ready && data?.capabilities?.execute !== true && <p>Execution unavailable: {data?.capabilities?.execute_reason || data?.capabilities?.reason || 'This preview cannot currently be executed.'}</p>}
    <footer className="remediation-impact__actions"><button type="button" className="remediation-impact__run" disabled={readOnly || !ready || !onRun || data?.capabilities?.execute !== true || runBusy || saving}
      onClick={() => onRun(selected, data)}>{runBusy ? 'Remediation is running…' : 'Approve plan and start'}</button>
      <button type="button" disabled={!validPolicy(data?.active_policy) || runBusy} onClick={() => { setPolicy({ ...data.active_policy }); setFilter(null) }}>Reset to active</button>
      <button type="button" disabled={readOnly || !ready || data?.capabilities?.save_future !== true || saving || runBusy} onClick={save}>{saving ? 'Saving…' : 'Save as default for future runs'}</button>
    </footer>
  </section>
}
