import { useEffect, useRef, useState } from 'react'
import { matchesWorkflow } from './remediationInboxModel.js'

const TABS = [['review', 'Needs review'], ['awaiting-validation', 'Processing'], ['completed', 'Completed']]

export default function ReviewQueueTabs({ queue, decisions, scanId, value, onChange, disabled }) {
  const counts = TABS.map(([key]) => queue.filter(row => matchesWorkflow(row, key, decisions)).length)
  const previous = useRef(null)
  const [change, setChange] = useState(null)
  const signature = counts.join(':')
  useEffect(() => {
    const before = previous.current
    previous.current = { scanId, counts }
    if (!before || before.scanId !== scanId) { setChange(null); return }
    const deltas = counts.map((count, i) => count - before.counts[i])
    if (deltas.some(Boolean)) setChange({ scanId, deltas })
    const timer = setTimeout(() => setChange(null), 2200)
    return () => clearTimeout(timer)
  }, [signature, scanId]) // Counts only; unrelated refreshes must not replay motion.
  const selected = ['needs-review', 'manual', 'blocked'].includes(value) ? 'review' : value
  return <div className="review-queue-tabs" role="group" aria-label="Review queues">
    {TABS.map(([key, label], i) => {
      const delta = change?.scanId === scanId ? change.deltas[i] : 0
      const positive = (key === 'review' && delta < 0) || (key === 'completed' && delta > 0)
      return <button key={key} type="button" aria-pressed={selected === key} disabled={disabled} onClick={() => onChange(key)}>
        <span>{label}</span><strong>{counts[i]}</strong>
        {!!delta && <span key={`${signature}:${i}`} className={`review-queue-delta${positive ? ' positive' : ''}`} aria-hidden="true">{delta > 0 ? '+' : '−'}{Math.abs(delta)}</span>}
      </button>
    })}
  </div>
}
