import { useEffect, useRef } from 'react'
import RemediationModeDiagram from './RemediationModeDiagram.jsx'
import './remediation-plan-dialog.css'

export default function RemediationPlanDialog({ open, onClose, children }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    if (!open) return
    const trigger = document.activeElement
    dialog.showModal()
    return () => { dialog.close(); if (trigger?.isConnected) trigger.focus() }
  }, [open])
  return <dialog ref={ref} className="remediation-plan-dialog" aria-label="Remediation plan"
    onCancel={event => { event.preventDefault(); if (!ref.current.querySelector('[role="dialog"]')) onClose() }}>
    <header className="remediation-plan-dialog__header"><h2>Remediation plan</h2>
      <button type="button" onClick={onClose} aria-label="Close remediation plan">Close</button></header>
    <p>Answer each question before starting. Closing this window does not start remediation.</p>
    {children}
    <details><summary>How modes work</summary><RemediationModeDiagram /></details>
  </dialog>
}
