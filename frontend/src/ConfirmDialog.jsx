import { useState, useEffect } from 'react'

let _open = null

export function confirm({ title, message, warning, facts, variant = 'default', presentation = 'dialog', confirmLabel = 'Confirm', cancelLabel = 'Cancel' } = {}) {
  return new Promise((resolve) => {
    if (!_open) { resolve(window.confirm([message, warning].filter(Boolean).join('\n\n'))); return }
    _open({ type: 'confirm', title, message, warning, facts, variant, presentation, confirmLabel, cancelLabel, resolve,
      returnFocus: document.activeElement })
  })
}

export function notify({ title, message, actionLabel, onAction, duration = 7000 } = {}) {
  if (!_open) return
  _open({ type: 'notice', title, message, actionLabel, onAction, duration,
    variant: 'activation', presentation: 'toast' })
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

const settle = (current, setState, value) => {
  setState(null)
  if (current.resolve) current.resolve(value)
  if (current.returnFocus && current.returnFocus.isConnected) {
    queueMicrotask(() => current.returnFocus.focus())
  }
}

export default function ConfirmDialog() {
  const [state, setState] = useState(null)
  useEffect(() => { _open = setState; return () => { _open = null } }, [])
  useEffect(() => {
    if (!state) return undefined
    const dismiss = () => settle(state, setState, state.type === 'confirm' ? false : undefined)
    const onKeyDown = (event) => { if (event.key === 'Escape') dismiss() }
    document.addEventListener('keydown', onKeyDown)
    const timer = state.type === 'notice' && state.duration > 0
      ? window.setTimeout(dismiss, state.duration)
      : null
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (timer) window.clearTimeout(timer)
    }
  }, [state])
  if (!state) return null
  const vt = VARIANTS[state.variant] || VARIANTS.default
  const isAlert = state.type === 'alert'
  const isNotice = state.type === 'notice'
  const isToast = state.presentation === 'toast'
  const finish = (val) => settle(state, setState, val)
  const takeAction = () => {
    if (isNotice && state.onAction) state.onAction()
    finish(isAlert ? undefined : true)
  }
  const handleBackdrop = (e) => { if (e.target === e.currentTarget) finish(isAlert ? undefined : false) }
  const content = (
    <div style={{ width:isToast ? 'min(92vw,470px)' : 'min(93vw,520px)', borderRadius:isToast ? 12 : 16, overflow:'hidden',
      border:isToast ? '1px solid #d8dee9' : 'none',
      boxShadow:isToast ? '0 16px 40px rgba(15,23,42,.18)' : '0 32px 72px rgba(0,0,0,.38)',
      animation:isToast ? 'cd-toast-in .22s cubic-bezier(.22,1,.36,1)' : 'cd-slide .22s cubic-bezier(.22,1,.36,1)',
      background:'#ffffff', pointerEvents:'auto' }}>
      <div style={{ background:isToast ? '#fff' : vt.bg, padding:isToast ? '16px 18px 8px' : '18px 22px', display:'flex', gap:12, alignItems:'center' }}>
        <div aria-hidden="true" style={{ width:30, height:30, borderRadius:9, display:'grid', placeItems:'center',
          fontSize:16, background:isToast ? '#f0eaf1' : 'rgba(255,255,255,.14)', color:isToast ? '#51314f' : '#fff' }}>{vt.icon}</div>
        <div id="cd-title" style={{ color:isToast ? '#172033' : '#fff', fontWeight:700, fontSize:17, lineHeight:1.35, flex:1 }}>
          {state.title || (isAlert ? 'Notice' : 'Confirm action')}
        </div>
        {isToast && <button aria-label="Dismiss" onClick={() => finish(isNotice ? undefined : false)} style={{ border:0, background:'transparent', color:'#64748b', cursor:'pointer', fontSize:20, lineHeight:1 }}>×</button>}
      </div>
      {state.message && (
        <div style={{ padding:isToast ? '8px 18px 0 60px' : '18px 22px 0', fontSize:14, color:'#334155', lineHeight:1.55, whiteSpace:'pre-wrap' }}>
          {state.message}
        </div>
      )}
      {Array.isArray(state.facts) && state.facts.length > 0 && (
        <dl style={{ margin:isToast ? '14px 18px 0 60px' : '16px 22px 0', display:'grid', gridTemplateColumns:isToast ? '1fr' : 'repeat(3,minmax(0,1fr))',
          border:'1px solid #e2e8f0', borderRadius:10, overflow:'hidden' }}>
          {state.facts.map((fact, index) => <div key={fact.label} style={{ padding:isToast ? '9px 11px' : '12px 13px', minWidth:0,
            borderLeft:!isToast && index ? '1px solid #e2e8f0' : 'none', borderTop:isToast && index ? '1px solid #e2e8f0' : 'none',
            background:'#f8fafc', display:isToast ? 'flex' : 'block', justifyContent:'space-between', gap:12 }}>
            <dt style={{ fontSize:isToast ? 12 : 10.5, textTransform:isToast ? 'none' : 'uppercase', letterSpacing:isToast ? 0 : '.05em', color:'#64748b', fontWeight:700 }}>{fact.label}</dt>
            <dd style={{ margin:isToast ? 0 : '5px 0 0', fontSize:13.5, lineHeight:1.35, color:'#172033', fontWeight:650, overflowWrap:'anywhere', textAlign:isToast ? 'right' : 'left' }}>{fact.value}</dd>
          </div>)}
        </dl>
      )}
      {state.warning && (
        <div style={{ margin:isToast ? '12px 18px 0 60px' : '14px 24px 0', padding:'11px 15px',
          background:'#fffbeb', border:'1px solid #fcd34d', borderRadius:9,
          fontSize:13.5, color:'#78350f', lineHeight:1.5 }}>
          {state.warning}
        </div>
      )}
      <div style={{ padding:isToast ? '16px 18px 16px 60px' : '18px 24px 22px', display:'flex', justifyContent:'flex-end', gap:10 }}>
        {!isAlert && !isNotice && (
          <button onClick={() => finish(false)} style={{ padding:'8px 16px', borderRadius:8,
            border:'1px solid #cbd5e1', background:'#fff', color:'#475569',
            cursor:'pointer', fontWeight:600, fontSize:14 }}>
            {state.cancelLabel || 'Cancel'}
          </button>
        )}
        {(!isNotice || state.actionLabel) && <button autoFocus={!isToast} onClick={takeAction}
          style={{ padding:'8px 17px', borderRadius:8, border:'none', background:isToast ? '#51314f' : vt.btnBg,
            color:'#fff', cursor:'pointer', fontWeight:650, fontSize:14,
            boxShadow:isToast ? 'none' : `0 3px 10px ${vt.btnShadow}` }}>
          {isNotice ? state.actionLabel : isAlert ? 'OK' : (state.confirmLabel || 'Confirm')}
        </button>}
      </div>
    </div>
  )
  if (isToast) return (
    <div role={isNotice ? 'status' : 'alertdialog'} aria-live={isNotice ? 'polite' : undefined}
      aria-modal={isNotice ? undefined : 'false'} aria-labelledby="cd-title"
      style={{ position:'fixed', zIndex:9999, top:18, right:18, pointerEvents:'none' }}>
      {content}
      <style>{`@keyframes cd-toast-in { from { transform:translateY(-12px);opacity:0 } to { transform:translateY(0);opacity:1 } }`}</style>
    </div>
  )
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="cd-title" onClick={handleBackdrop}
      style={{ position:'fixed', inset:0, zIndex:9999, display:'flex', alignItems:'center',
        justifyContent:'center', background:'rgba(15,23,42,0.6)', backdropFilter:'blur(4px)',
        animation:'cd-fade .15s ease' }}>
      {content}
      <style>{`@keyframes cd-fade { from { opacity:0 } to { opacity:1 } } @keyframes cd-slide { from { transform:scale(.9) translateY(20px);opacity:0 } to { transform:scale(1) translateY(0);opacity:1 } }`}</style>
    </div>
  )
}
