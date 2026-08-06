import { useState } from 'react'

// On-demand "AI insight" for a chart. Click the eye → brief analysis → a 1–2 sentence
// takeaway. Text is computed from the chart's real data (deterministic); swap `text`
// for an LLM call to make it open-ended.
export default function Insight({ text }) {
  const [state, setState] = useState('idle') // idle | loading | shown
  const toggle = () => {
    if (state !== 'idle') { setState('idle'); return }
    setState('loading')
    setTimeout(() => setState('shown'), 750)
  }
  return (
    <>
      <button className={state !== 'idle' ? 'insighteye on' : 'insighteye'} aria-label="AI insight" title="AI insight — analyze this chart" onClick={toggle}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" /><circle cx="12" cy="12" r="3" /></svg>
      </button>
      {state === 'loading' && <div className="insightbox"><span className="spinner" /> analyzing…</div>}
      {state === 'shown' && <div className="insightbox"><span className="aibadge">AI</span><span>{text}</span></div>}
    </>
  )
}
