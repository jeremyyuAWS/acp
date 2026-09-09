import { useId } from 'react'
import './remediation-waterfall-impact.css'

const ROUTES = [
  ['rule_based', 'Rule-based fixes planned', 'Rules can prepare these changes. Any required approval still comes first.'],
  ['ai', 'AI may help', 'AI can try these findings. A useful suggestion is not guaranteed.'],
  ['person', 'Needs a person', 'Content decisions or work without an available automated route.'],
  ['blocked', 'Cannot plan yet', 'Missing evidence or other blockers need attention first.'],
]
const validCount = value => Number.isSafeInteger(value) && value >= 0

// Keep finding instances mutually exclusive; model calls and proposal cards are not findings.
export function deriveWaterfallImpact(data) {
  const groups = Object.fromEntries(ROUTES.map(([key]) => [key, { count: 0, rows: [] }]))
  const ids = new Set()
  let rowsComplete = Array.isArray(data?.findings)
  for (const row of Array.isArray(data?.findings) ? data.findings : []) {
    if (!row || !validCount(row.finding_count) || (row.id && ids.has(row.id))) {
      rowsComplete = false
      continue
    }
    if (row.id) ids.add(row.id)
    let key
    if (row.lane === 'blocked') key = 'blocked'
    else if (row.lane === 'manual') key = 'person'
    else if (row.origin === 'rule_based' && ['automatic', 'review'].includes(row.lane)) key = 'rule_based'
    // `automatic` as well as `review`: under standing approval the backend forecasts
    // eligible AI rows into the automatic lane. They are still AI work and belong in
    // this segment; without the extra lane they match no branch, drop out of every
    // group, and break the counted === total invariant that gates the whole chart --
    // so the panel would silently degrade to "Not yet known" exactly when AI is most active.
    else if (row.origin === 'ai' && ['automatic', 'review'].includes(row.lane) && data?.policy?.ai > 0) key = 'ai'
    if (!key) { rowsComplete = false; continue }
    groups[key].count += row.finding_count
    groups[key].rows.push(row)
  }
  const counted = Object.values(groups).reduce((sum, group) => sum + group.count, 0)
  const total = data?.open?.findings
  const complete = rowsComplete && validCount(total) && counted === total &&
    data?.integrity?.complete === true && data?.integrity?.open_equals_lane_sum === true
  return { groups, total: validCount(total) ? total : null, complete }
}

export default function RemediationWaterfallImpact({ data, onInspectAI, onInspectRoute }) {
  const titleId = useId()
  const { groups, total, complete } = deriveWaterfallImpact(data)
  const countText = count => complete ? count.toLocaleString() : count > 0 ? `${count.toLocaleString()} recorded` : 'Not yet known'
  const aiEnabled = data?.policy?.ai > 0
  const zeroBudget = data?.policy?.ai_budget_usd !== undefined && Number(data.policy.ai_budget_usd) === 0
  return <section className="waterfall-impact" aria-labelledby={titleId}>
    <p className="waterfall-impact__eyebrow">Before you start · Plan preview</p>
    <h3 id={titleId}>Impact of your remediation plan</h3>
    <p>{total === null ? 'Selected finding total is not yet known.' : `${total.toLocaleString()} unresolved findings in this preview.`}
      {' '}{validCount(data?.open?.files) && `${data.open.files.toLocaleString()} selected files with findings.`}</p>
    <p>These are planned routes, not completed fixes. Extra help from each AI model is not measured yet.</p>
    {!complete && <p className="waterfall-impact__incomplete">A complete chart is not available because the finding counts could not be fully reconciled. Recorded counts below may be incomplete.</p>}
    {complete && total > 0 && <div className="waterfall-impact__stack" aria-hidden="true">
      {ROUTES.map(([key]) => groups[key].count > 0 && <span key={key} className={`waterfall-impact__color--${key}`} style={{ width: `${groups[key].count / total * 100}%` }} />)}
    </div>}
    <table className="waterfall-impact__table">
      <caption>Selected findings by planned route</caption>
      <thead><tr><th scope="col">Planned route</th><th scope="col">Finding instances</th></tr></thead>
      <tbody>{ROUTES.map(([key, label, description]) => {
        const group = groups[key]
        const inspect = key === 'ai' ? onInspectAI : onInspectRoute
        return <tr key={key}>
          <th scope="row">
            <span className={`waterfall-impact__dot waterfall-impact__color--${key}`} aria-hidden="true" />
            {label}
            <span className="waterfall-impact__description">{key === 'rule_based' && data?.policy?.rule_based === 0 ? 'A person must approve every rule-based change before it is applied.' : description}</span>
            {inspect && group.rows.length > 0 && <button type="button" onClick={() => key === 'ai' ? inspect(group.rows) : inspect(key, group.rows)}>
              {key === 'ai' ? 'See findings and AI details' : `View ${label.toLowerCase()}`}
            </button>}
          </th>
          <td><strong>{countText(group.count)}</strong>
            {complete && total > 0 && <span className="waterfall-impact__track" aria-hidden="true"><span className={`waterfall-impact__color--${key}`} style={{ width: `${group.count / total * 100}%` }} /></span>}
          </td>
        </tr>
      })}</tbody>
    </table>
    {!aiEnabled ? <p>Rules only is selected. This plan will not ask AI for new suggestions.</p> : zeroBudget ?
      <p>The AI spending limit is $0. No paid AI requests are allowed; AI eligibility does not mean a request will run.</p> :
      <p>AI suggestions need your approval before application. Another model may be tried when the first response is empty or cut short and spending permits.</p>}
    <p className="waterfall-impact__process">{aiEnabled ? 'Try rules → Ask AI for remaining supported work → Review the suggestion → Apply approved changes and check the result' : 'Try rules → Review changes when required → Apply approved changes and check the result'}</p>
    <p>Exploring this chart does not start remediation or ask an AI model to generate anything. Use “Approve plan and start” when you are ready.</p>
  </section>
}
