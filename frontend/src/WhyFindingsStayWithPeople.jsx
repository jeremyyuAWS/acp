import { ROUTING_REASON_COPY, countLabel, policyPreviewIntegrity } from './automationPolicyContract.js'

function Axis({ title, rows, keyName }) {
  if (!Array.isArray(rows) || rows.length === 0) return null
  return <div className="automation-policy__axis"><strong>{title}</strong><ul>
    {rows.map((row) => <li key={row[keyName]}><span>{row[keyName]}</span><span>{countLabel(row)}</span></li>)}
  </ul></div>
}

export default function WhyFindingsStayWithPeople({ preview }) {
  if (!policyPreviewIntegrity(preview).valid) return null
  const people = preview.lanes.review.findings + preview.lanes.protected.findings
  const unknown = preview.integrity?.unknown_primary_reason
  const reasons = (preview.reasons || []).filter((item) => ROUTING_REASON_COPY[item.reason])
  if (people === 0) return null
  return <details className="automation-policy__breakdown automation-policy__why-people">
    <summary>Why {people} findings stay with people</summary>
    <div className="automation-policy__categories">
      {reasons.map((item) => {
        const [label, description] = ROUTING_REASON_COPY[item.reason]
        return <div className="automation-policy__category" key={item.reason}>
          <div><strong>{label}</strong><span>{description}</span></div><b>{countLabel(item)}</b>
          <details><summary>View by criterion and format</summary><div className="automation-policy__drilldown">
            <Axis title="WCAG criterion" rows={item.criteria} keyName="criterion" />
            <Axis title="Format" rows={item.formats} keyName="format" />
          </div></details>
        </div>
      })}
      {unknown?.findings > 0 && <div className="automation-policy__category is-unknown">
        <div><strong>Reason unavailable</strong><span>ACP has not recorded a primary routing reason for this work.</span></div>
        <b>{countLabel(unknown)}</b>
      </div>}
    </div>
  </details>
}
