import { useEffect, useRef, useState } from 'react'
import { workflowStatusOf, issueLabel } from './remediationInboxModel.js'

/** A short confirmation when durable verification moves a row out of the work queue. */
export default function CompletionDrain({ queue, decisions, scanId, active }) {
  const previous = useRef({ scanId, statuses: new Map(queue.map(row => [row.id, workflowStatusOf(row, decisions)])) })
  const [moved, setMoved] = useState([])
  useEffect(() => {
    const statuses = new Map(queue.map(row => [row.id, workflowStatusOf(row, decisions)]))
    const changed = previous.current.scanId === scanId
      ? queue.filter(row => statuses.get(row.id) === 'completed'
        && previous.current.statuses.has(row.id) && previous.current.statuses.get(row.id) !== 'completed') : []
    previous.current = { scanId, statuses }
    if (changed.length) setMoved(changed)
  }, [queue, decisions, scanId])
  useEffect(() => {
    if (!moved.length) return undefined
    const timer = setTimeout(() => setMoved([]), 650)
    return () => clearTimeout(timer)
  }, [moved])
  if (!active || !moved.length) return null
  return <div className="rinbox-completion-drain" role="status" aria-live="polite">
    {moved.length === 1 ? `${issueLabel(moved[0])} moved to Completed` : `${moved.length} items moved to Completed`}
  </div>
}
