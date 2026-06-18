import { useState, useEffect } from 'react'
import Rubric from './Rubric.jsx'
import WcagCoverage from './WcagCoverage.jsx'

// Platform settings, behind the header cog — gated to the Platform Admin. Holds
// the scoring rules (Rubric) and the validation coverage (WCAG 2.1 + 2.2 matrix),
// i.e. the configuration an admin owns, kept out of the day-to-day workflow tabs.
export default function Settings({ onClose, onRubricSaved }) {
  const [tab, setTab] = useState('rules')
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="setoverlay" role="dialog" aria-label="Platform settings" onClick={onClose}>
      <div className="setpanel" onClick={(e) => e.stopPropagation()}>
        <div className="sethead">
          <div><b>⚙ Platform settings</b><span className="muted"> · admin · rules &amp; validation</span></div>
          <button className="ghost small" aria-label="Close settings" onClick={onClose}>✕</button>
        </div>
        <div className="subtabs" role="tablist" aria-label="Settings sections">
          <button role="tab" aria-selected={tab === 'rules'} className={tab === 'rules' ? 'fchip on' : 'fchip'} onClick={() => setTab('rules')}>Scoring rules</button>
          <button role="tab" aria-selected={tab === 'validation'} className={tab === 'validation' ? 'fchip on' : 'fchip'} onClick={() => setTab('validation')}>Validation coverage</button>
        </div>
        <div className="setbody">
          {tab === 'rules' && <Rubric onSaved={onRubricSaved} />}
          {tab === 'validation' && <WcagCoverage />}
        </div>
      </div>
    </div>
  )
}
