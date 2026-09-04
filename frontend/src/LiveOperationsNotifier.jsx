import { useEffect, useRef, useState } from 'react'
import { openAdminActivityStream } from './api.js'

const LABEL = { discover: 'Discovery', assess: 'Assessment', remediate: 'Remediation' }

export function newStageStarts(previous = [], current = []) {
  const prior = new Set(previous.filter((run) => run.status !== 'recent').map((run) => `${run.scan_id}:${run.stage}`))
  return current.filter((run) => LABEL[run.stage] && run.status !== 'recent' && (Number(run.running) > 0 || Number(run.queued) > 0))
    .filter((run) => !prior.has(`${run.scan_id}:${run.stage}`))
}

function ding() {
  const AudioContext = window.AudioContext || window.webkitAudioContext
  if (!AudioContext) return
  const context = new AudioContext()
  const gain = context.createGain()
  gain.gain.setValueAtTime(0.0001, context.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.08, context.currentTime + 0.015)
  gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.42)
  gain.connect(context.destination)
  ;[660, 880].forEach((frequency, index) => {
    const oscillator = context.createOscillator()
    oscillator.frequency.value = frequency
    oscillator.connect(gain)
    oscillator.start(context.currentTime + index * 0.08)
    oscillator.stop(context.currentTime + 0.32 + index * 0.08)
  })
  window.setTimeout(() => context.close(), 700)
}

export function LiveOperationsToast({ run, onOpen, onDismiss }) {
  if (!run) return null
  const label = LABEL[run.stage] || run.stage
  return <div role="status" aria-live="polite" aria-atomic="true"
    style={{ position: 'fixed', right: 18, top: 18, zIndex: 10000, width: 'min(360px,calc(100vw - 36px))',
      textAlign: 'left', padding: 14, borderRadius: 10, border: '1px solid var(--success-fg)', borderLeft: '5px solid var(--success-fg-strong)',
      background: 'var(--panel)', color: 'var(--text)', boxShadow: '0 10px 30px rgba(20,16,24,.22)' }}>
    <span style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}><b>{label} started</b>
      <button type="button" className="ghost small" aria-label="Dismiss notification" onClick={() => onDismiss?.()}>×</button></span>
    <button type="button" className="ghost" onClick={() => onOpen?.(run)}
      style={{ display: 'block', width: '100%', textAlign: 'left', padding: 0, border: 0, background: 'transparent' }}>
      <span className="muted" style={{ display: 'block', marginTop: 4 }}>{run.owner} · {run.total || 0} documents</span>
      <span style={{ display: 'block', marginTop: 8, color: 'var(--success-fg)', fontWeight: 700 }}>Open Live Operations →</span>
    </button>
  </div>
}

export default function LiveOperationsNotifier({ onOpen }) {
  const [run, setRun] = useState(null)
  const previous = useRef(null)
  const seen = useRef(new Set())
  const soundArmed = useRef(false)
  const dismissTimer = useRef(null)

  useEffect(() => {
    const arm = () => { soundArmed.current = true }
    window.addEventListener('pointerdown', arm, { once: true })
    window.addEventListener('keydown', arm, { once: true })
    const stream = openAdminActivityStream({ onMessage: (snapshot) => {
      const current = snapshot?.runs || []
      if (previous.current === null) {
        current.forEach((item) => seen.current.add(`${item.scan_id}:${item.stage}`))
        previous.current = current
        return
      }
      const starts = newStageStarts(previous.current, current).filter((item) => !seen.current.has(`${item.scan_id}:${item.stage}`))
      current.forEach((item) => seen.current.add(`${item.scan_id}:${item.stage}`))
      previous.current = current
      if (!starts.length) return
      const latest = starts.at(-1)
      setRun(latest)
      if (soundArmed.current) { try { ding() } catch { /* notification sound is best effort */ } }
      window.clearTimeout(dismissTimer.current)
      dismissTimer.current = window.setTimeout(() => setRun(null), 8000)
    } })
    return () => {
      stream.close()
      window.clearTimeout(dismissTimer.current)
      window.removeEventListener('pointerdown', arm)
      window.removeEventListener('keydown', arm)
    }
  }, [])

  return <LiveOperationsToast run={run} onDismiss={() => setRun(null)} onOpen={(item) => { setRun(null); onOpen?.(item) }} />
}
