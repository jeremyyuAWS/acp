import { useEffect, useRef, useState } from 'react'
import { openAdminActivityStream } from './api.js'

const LABEL = { discover: 'Discovery', assess: 'Assessment', remediate: 'Remediation' }

export function newStageStarts(previous = [], current = []) {
  const prior = new Set(previous.filter((run) => run.status !== 'recent').map((run) => `${run.scan_id}:${run.stage}`))
  return current.filter((run) => LABEL[run.stage] && run.status !== 'recent' && (Number(run.running) > 0 || Number(run.queued) > 0))
    .filter((run) => !prior.has(`${run.scan_id}:${run.stage}`))
}

export function newStageCompletions(previous = [], current = []) {
  const prior = new Map(previous.map((run) => [`${run.scan_id}:${run.stage}`, run]))
  return current.filter((run) => {
    const before = prior.get(`${run.scan_id}:${run.stage}`)
    return LABEL[run.stage] && run.status === 'recent' && before && before.status !== 'recent'
      && (Number(before.running) > 0 || Number(before.queued) > 0)
  })
}

export function playNotificationSound(kind = 'started') {
  const AudioContext = window.AudioContext || window.webkitAudioContext
  if (!AudioContext) return
  const context = new AudioContext()
  const gain = context.createGain()
  gain.gain.setValueAtTime(0.0001, context.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.08, context.currentTime + 0.015)
  gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + (kind === 'completed' ? 0.52 : 0.42))
  gain.connect(context.destination)
  const notes = kind === 'completed' ? [523, 659, 784] : [660, 880]
  notes.forEach((frequency, index) => {
    const oscillator = context.createOscillator()
    oscillator.frequency.value = frequency
    oscillator.connect(gain)
    oscillator.start(context.currentTime + index * (kind === 'completed' ? 0.1 : 0.08))
    oscillator.stop(context.currentTime + 0.28 + index * 0.1)
  })
  window.setTimeout(() => context.close(), 750)
}

export function LiveOperationsToast({ run, kind = 'started', onOpen, onDismiss }) {
  if (!run) return null
  const label = LABEL[run.stage] || run.stage
  const completed = kind === 'completed'
  const tone = completed ? 'var(--success-fg)' : 'var(--info-fg)'
  const strongTone = completed ? 'var(--success-fg-strong)' : 'var(--info-fg)'
  return <div role="status" aria-live="polite" aria-atomic="true"
    data-notification-kind={kind}
    style={{ position: 'fixed', right: 14, top: 14, zIndex: 10000, width: 'min(320px,calc(100vw - 28px))',
      textAlign: 'left', padding: 11, borderRadius: 8, border: `1px solid ${tone}`, borderLeft: `4px solid ${strongTone}`,
      // --panel is not a defined application token and therefore resolved to transparent.
      // --surface is the shared, explicitly opaque card token (with a defensive white fallback).
      background: 'var(--surface, #fff)', opacity: 1, isolation: 'isolate',
      color: 'var(--ink)', boxShadow: '0 10px 26px rgba(20,16,24,.24)', fontSize: 13 }}>
    <span style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}><b>{label} {completed ? 'complete' : 'started'}</b>
      <button type="button" className="ghost small" aria-label="Dismiss notification" onClick={() => onDismiss?.()}>×</button></span>
    <button type="button" className="ghost" onClick={() => onOpen?.(run)}
      style={{ display: 'block', width: '100%', textAlign: 'left', padding: 0, border: 0, background: 'transparent' }}>
      <span className="muted" style={{ display: 'block', marginTop: 3 }}>{run.owner} · {run.total || 0} documents</span>
      <span style={{ display: 'block', marginTop: 6, color: tone, fontWeight: 700 }}>Open Live Operations →</span>
    </button>
  </div>
}

export default function LiveOperationsNotifier({ onOpen }) {
  const [notice, setNotice] = useState(null)
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
      const completions = newStageCompletions(previous.current, current)
      current.forEach((item) => seen.current.add(`${item.scan_id}:${item.stage}`))
      previous.current = current
      if (!starts.length && !completions.length) return
      const kind = completions.length ? 'completed' : 'started'
      const latest = (completions.length ? completions : starts).at(-1)
      setNotice({ run: latest, kind })
      if (soundArmed.current) { try { playNotificationSound(kind) } catch { /* notification sound is best effort */ } }
      window.clearTimeout(dismissTimer.current)
      dismissTimer.current = window.setTimeout(() => setNotice(null), 7000)
    } })
    return () => {
      stream.close()
      window.clearTimeout(dismissTimer.current)
      window.removeEventListener('pointerdown', arm)
      window.removeEventListener('keydown', arm)
    }
  }, [])

  return <LiveOperationsToast run={notice?.run} kind={notice?.kind} onDismiss={() => setNotice(null)} onOpen={(item) => { setNotice(null); onOpen?.(item) }} />
}
