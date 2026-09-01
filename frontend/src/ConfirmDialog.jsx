import { useState, useEffect } from 'react'

let _open = null

export function confirm({ title, message, warning, facts, variant = 'default', confirmLabel = 'Confirm', cancelLabel = 'Cancel' } = {}) {
  return new Promise((resolve) => {
    if (!_open) { resolve(window.confirm([message, warning].filter(Boolean).join('\n\n'))); return }
    _open({ type: 'confirm', title, message, warning, facts, variant, confirmLabel, cancelLabel, resolve })
  })
}

export function alert({ title, message } = {}) {
  return new Promise((resolve) => {
    if (!_open) { window.alert(message); resolve(); return }
    _open({ type: 'alert', title, message, resolve })
  })
}

const VARIANTS = {
  default: { bg: 'linear-gradient(135deg,#2563eb 0%,#0ea5e9 100%)', icon: 'ℹ️', btnBg: '#2563eb', btnShadow: '#2563eb55' },
  warning: { bg: 'linear-gradient(135deg,#d97706 0%,#f59e0b 100%)', icon: '⚠️', btnBg: '#d97706', btnShadow: '#d9770655' },
  danger:  { bg: 'linear-gradient(135deg,#dc2626 0%,#ef4444 100%)', icon: '🗑️', btnBg: '#dc2626', btnShadow: '#dc262655' },
  info:    { bg: 'linear-gradient(135deg,#7c3aed 0%,#6366f1 100%)', icon: '📋', btnBg: '#7c3aed', btnShadow: '#7c3aed55' },
  activation: { bg: '#35233b', icon: '✓', btnBg: '#51314f', btnShadow: '#51314f44' },
}

export default function ConfirmDialog() {
  const [state, setState] = useState(null)
  useEffect(() => { _open = setState; return () => { _open = null } }, [])
  if (!state) return null
  const vt = VARIANTS[state.variant] || VARIANTS.default
  const isAlert = state.type === 'alert'
  const finish = (val) => { const res = state.resolve; setState(null); res(val) }
  const handleBackdrop = (e) => { if (e.target === e.currentTarget) finish(isAlert ? undefined : false) }
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="cd-title" onClick={handleBackdrop}
      style={{ position:'fixed', inset:0, zIndex:9999, display:'flex', alignItems:'center',
        justifyContent:'center', background:'rgba(15,23,42,0.6)', backdropFilter:'blur(4px)',
        animation:'cd-fade .15s ease' }}>
      <div style={{ width:'min(93vw,520px)', borderRadius:16, overflow:'hidden',
        boxShadow:'0 32px 72px rgba(0,0,0,.38)', animation:'cd-slide .22s cubic-bezier(.22,1,.36,1)',
        background:'#ffffff' }}>
        <div style={{ background:vt.bg, padding:'18px 22px', display:'flex', gap:12, alignItems:'center' }}>
          <div aria-hidden="true" style={{ width:30, height:30, borderRadius:9, display:'grid', placeItems:'center',
            fontSize:16, background:'rgba(255,255,255,.14)', color:'#fff' }}>{vt.icon}</div>
          <div id="cd-title" style={{ color:'#fff', fontWeight:700, fontSize:17, lineHeight:1.35 }}>
            {state.title || (isAlert ? 'Notice' : 'Confirm action')}
          </div>
        </div>
        {state.message && (
          <div style={{ padding:'18px 22px 0', fontSize:14, color:'#1e293b', lineHeight:1.6, whiteSpace:'pre-wrap' }}>
            {state.message}
          </div>
        )}
        {Array.isArray(state.facts) && state.facts.length > 0 && (
          <dl style={{ margin:'16px 22px 0', display:'grid', gridTemplateColumns:'repeat(3,minmax(0,1fr))',
            border:'1px solid #e2e8f0', borderRadius:12, overflow:'hidden' }}>
            {state.facts.map((fact, index) => <div key={fact.label} style={{ padding:'12px 13px', minWidth:0,
              borderLeft:index ? '1px solid #e2e8f0' : 'none', background:'#f8fafc' }}>
              <dt style={{ fontSize:10.5, textTransform:'uppercase', letterSpacing:'.05em', color:'#64748b', fontWeight:700 }}>{fact.label}</dt>
              <dd style={{ margin:'5px 0 0', fontSize:13.5, lineHeight:1.35, color:'#172033', fontWeight:650, overflowWrap:'anywhere' }}>{fact.value}</dd>
            </div>)}
          </dl>
        )}
        {state.warning && (
          <div style={{ margin:'14px 24px 0', padding:'11px 15px',
            background:'#fffbeb', border:'1.5px solid #fcd34d', borderRadius:10,
            fontSize:13.5, color:'#78350f', lineHeight:1.55 }}>
            {state.warning}
          </div>
        )}
        <div style={{ padding:'18px 24px 22px', display:'flex', justifyContent:'flex-end', gap:10 }}>
          {!isAlert && (
            <button onClick={() => finish(false)} style={{ padding:'9px 20px', borderRadius:9,
              border:'1.5px solid #cbd5e1', background:'#f8fafc', color:'#475569',
              cursor:'pointer', fontWeight:500, fontSize:14 }}>
              {state.cancelLabel || 'Cancel'}
            </button>
          )}
          <button autoFocus onClick={() => finish(isAlert ? undefined : true)}
            style={{ padding:'9px 22px', borderRadius:9, border:'none', background:vt.btnBg,
              color:'#fff', cursor:'pointer', fontWeight:600, fontSize:14,
              boxShadow:`0 3px 10px ${vt.btnShadow}` }}>
            {isAlert ? 'OK' : (state.confirmLabel || 'Confirm')}
          </button>
        </div>
      </div>
      <style>{`@keyframes cd-fade { from { opacity:0 } to { opacity:1 } } @keyframes cd-slide { from { transform:scale(.9) translateY(20px);opacity:0 } to { transform:scale(1) translateY(0);opacity:1 } }`}</style>
    </div>
  )
}
