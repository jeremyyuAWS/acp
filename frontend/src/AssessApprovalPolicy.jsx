import { useId, useState } from 'react'
import { CAPABILITY_FALLBACK } from './capability.js'
import { normalizeApprovalPolicy, approvalForCriterion, criterionCapabilityDescription } from './assessApprovalPolicy.js'

const OPTIONS = [
  ['automatic', 'Automatic (recommended)', 'Automatically approve supported fixes and valid AI suggestions. Only exceptions needing your input remain.'],
  ['review', 'Review proposed fixes', 'Ask for your approval before applying a proposed fix.'],
  ['custom', 'Customize by criterion', 'Choose which selected criteria require approval.'],
]
export default function AssessApprovalPolicy({ value, onChange, criteria = [], formats = [], capability = CAPABILITY_FALLBACK, disabled = false }) {
  const id = useId()
  const [query, setQuery] = useState('')
  const [reviewOnly, setReviewOnly] = useState(false)
  const policy = normalizeApprovalPolicy(value, criteria.map(row => row.code))
  const summary = policy.mode === 'automatic' ? 'Automatic approval · supported fixes and valid AI suggestions'
    : policy.mode === 'review' ? 'Review proposed fixes · approval required'
    : `Custom approval · ${policy.review_scs.length} selected criteria need review`
  const setMode = mode => onChange?.({...policy, mode})
  const setCriterion = (sc, action) => onChange?.({...policy, review_scs: action === 'review'
    ? [...new Set([...policy.review_scs, sc])].sort() : policy.review_scs.filter(code => code !== sc)})
  const visibleCriteria = criteria.filter(row => `${row.code} ${row.name}`.toLowerCase().includes(query.trim().toLowerCase())
    && (!reviewOnly || approvalForCriterion(policy, row.code) === 'review'))
  const setAll = action => onChange?.({...policy, review_scs: action === 'review' ? criteria.map(row => row.code).sort() : []})
  return <details className="assess-approval-policy" style={{borderTop:'1px solid var(--line)',padding:'12px 0',fontSize:12.5,lineHeight:1.55}}>
    <summary style={{cursor:'pointer',fontWeight:600}}>Fix approval <span className="muted" style={{fontWeight:400}}>· {summary}</span></summary>
    <fieldset disabled={disabled} style={{border:0,padding:0,margin:'10px 0'}}>
      <legend className="sr-only">Approval for fixes in this run</legend>
      {OPTIONS.map(([mode,label,description]) => <label key={mode} style={{display:'flex',alignItems:'flex-start',gap:8,padding:'7px 10px',border:'1px solid var(--line)',borderRadius:8,marginBottom:6,background:policy.mode === mode ? 'var(--ack-warn-bg, #fffbf4)' : 'var(--surface)'}}>
        <input type="radio" name={id} value={mode} checked={policy.mode === mode} onChange={() => setMode(mode)} style={{marginTop:4}} />
        <span><b>{label}</b><span className="muted" style={{display:'block',fontSize:12}}>{description}</span></span>
      </label>)}
      {policy.mode === 'custom' && <>
        <div style={{display:'flex',alignItems:'center',gap:8,flexWrap:'wrap',margin:'10px 0 6px'}}>
          <input type="search" aria-label="Search selected criteria" placeholder="Find criterion" value={query} onChange={e => setQuery(e.target.value)} style={{fontSize:12,width:180,maxWidth:'100%',padding:'6px 8px'}} />
          <label style={{display:'flex',alignItems:'center',gap:5,fontSize:12}}><input type="checkbox" checked={reviewOnly} onChange={e => setReviewOnly(e.target.checked)} />Review first only</label>
          <button type="button" onClick={() => setAll('automatic')} style={{fontSize:12,padding:'5px 8px'}}>All selected automatic</button>
          <button type="button" onClick={() => setAll('review')} style={{fontSize:12,padding:'5px 8px'}}>All selected review first</button>
        </div>
        <div style={{maxWidth:'100%',overflowX:'auto'}}><table style={{width:'100%',borderCollapse:'collapse',marginTop:10,fontSize:12}}>
        <caption style={{textAlign:'left',paddingBottom:6}}>Approval for selected criteria</caption>
        <thead><tr><th scope="col" style={{textAlign:'left'}}>Criterion / available repair</th><th scope="col" style={{textAlign:'left'}}>Approval</th></tr></thead>
        <tbody>{visibleCriteria.map(row => <tr key={row.code} style={{borderTop:'1px solid var(--line)'}}>
          <th scope="row" style={{textAlign:'left',fontWeight:400,padding:'8px 0'}}><b>{row.code} · {row.name}</b>
            {criterionCapabilityDescription(row.code, formats, capability).map(item => <span key={item.format} className="muted" style={{display:'block',fontSize:11.5}}>{item.format.toUpperCase()} · {item.label}</span>)}
          </th>
          <td style={{verticalAlign:'top',padding:'8px 0 8px 10px',width:135,whiteSpace:'nowrap'}}><select aria-label={`Approval for ${row.code}`} value={approvalForCriterion(policy,row.code)} onChange={e => setCriterion(row.code,e.target.value)}>
            <option value="automatic">Automatic</option><option value="review">Review first</option>
          </select></td>
        </tr>)}{visibleCriteria.length === 0 && <tr><td colSpan="2" className="muted" style={{padding:'8px 0'}}>No selected criteria match this view.</td></tr>}</tbody>
      </table></div></>}
    </fieldset>
    <p className="muted" style={{fontSize:12,margin:'6px 0 0'}}>Approval does not add an unsupported repair, bypass checks, or certify a document. Unsupported document edits, missing source content, and unsuccessful checks still need attention. This choice does not change assessment scope or automatic publication.</p>
  </details>
}
