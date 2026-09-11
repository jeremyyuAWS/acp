import { useRef } from 'react'
import { useDialog } from './a11y.js'
import { ResetMyData } from './Settings.jsx'

// Self-service only: this opens no administrative Settings tabs or reset-all action.
export default function MyDataDialog({ onClose }) {
  const panel = useRef(null)
  useDialog(panel, onClose)
  return <div className="setoverlay" role="dialog" aria-modal="true" aria-label="My data" onClick={onClose}>
    <div className="setpanel" ref={panel} tabIndex={-1} onClick={(event) => event.stopPropagation()} style={{ maxWidth: 640 }}>
      <header className="sethead"><b>My data</b><button className="ghost small" aria-label="Close my data" onClick={onClose}>✕</button></header>
      <div className="setbody"><ResetMyData /></div>
    </div>
  </div>
}
