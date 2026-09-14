import { useEffect, useRef, useState } from 'react'
import { openAdminActivityStream } from './api.js'

const LABEL = { discover: 'Discovery', assess: 'Assessment', remediate: 'Remediation' }

const STAGE_ORDER = { discover: 0, assess: 1, remediate: 2, release: 3 }
const stageKey = (run) => `${run.scan_id}:${run.stage}:${run.stage_run_id || ''}`

// Queue tails include assessment trace work. Canonical workflow completion is
// the assessment result boundary; trace settlement cannot announce it again.
export function notificationRuns(snapshot) {
  if (!Array.isArray(snapshot?.workflows)) return snapshot?.runs || []
  return snapshot.workflows.flatMap((workflow) => (workflow.stages || []).map((stage) => {
    const canonical = stage.canonical
    const complete = canonical ? canonical.state === 'succeeded'
      : stage.completion_recorded === true && stage.terminal_outcome === 'completed'
    const counts = canonical?.counts?.work_items || {}
    return {
      scan_id: workflow.scan_id, owner: workflow.owner_display_name,
      stage: stage.stage, stage_run_id: stage.stage_run_id || canonical?.execution_id,
      status: complete ? 'recent' : ['running', 'waiting'].includes(stage.status) ? 'active' : stage.status,
      running: stage.active ?? counts.processing ?? 0, queued: stage.waiting ?? counts.queued ?? 0,
      total: stage.total ?? counts.total ?? 0, completed: stage.completed ?? counts.completed ?? 0,
      completion_recorded: complete, terminal_outcome: complete ? 'completed' : stage.terminal_outcome,
      notification_source: canonical ? 'canonical' : 'lifecycle',
    }
  }))
}

export function newStageStarts(previous = [], current = []) {
  const prior = new Set(previous.filter((run) => run.status !== 'recent').map((run) => stageKey(run)))
  return current.filter((run) => LABEL[run.stage] && run.status !== 'recent' && (Number(run.running) > 0 || Number(run.queued) > 0))
    .filter((run) => !prior.has(stageKey(run)))
}

export function newStageCompletions(previous = [], current = []) {
  const prior = new Map(previous.map((run) => [stageKey(run), run]))
  return current.filter((run) => {
    const before = prior.get(stageKey(run))
    const laterAlreadyStarted = previous.some((other) => other.scan_id === run.scan_id
      && STAGE_ORDER[other.stage] > STAGE_ORDER[run.stage]
      && ['active', 'recent'].includes(other.status))
    return LABEL[run.stage] && run.status === 'recent' && run.completion_recorded === true
      && run.terminal_outcome === 'completed' && before && before.status === 'active'
      && !laterAlreadyStarted
      && (before.notification_source === 'canonical' || Number(before.running) > 0 || Number(before.queued) > 0)
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
  const completedSeen = useRef(new Set())
  const soundArmed = useRef(false)
  const dismissTimer = useRef(null)

  useEffect(() => {
    const arm = () => { soundArmed.current = true }
    window.addEventListener('pointerdown', arm, { once: true })
    window.addEventListener('keydown', arm, { once: true })
    const stream = openAdminActivityStream({ onMessage: (snapshot) => {
      const current = notificationRuns(snapshot)
      if (previous.current === null) {
        current.forEach((item) => {
          seen.current.add(stageKey(item))
          if (item.completion_recorded === true) completedSeen.current.add(stageKey(item))
        })
        previous.current = current
        return
      }
      const starts = newStageStarts(previous.current, current).filter((item) =>
        !seen.current.has(stageKey(item)) && (item.stage_run_id ||
          !Array.from(seen.current).some((key) => key.startsWith(`${item.scan_id}:${item.stage}:`))))
      const completions = newStageCompletions(previous.current, current)
        .filter((item) => !completedSeen.current.has(stageKey(item)))
      current.forEach((item) => {
        if (item.completion_recorded === true) completedSeen.current.add(stageKey(item))
      })
      current.forEach((item) => seen.current.add(stageKey(item)))
      previous.current = current
      if (!starts.length && !completions.length) return
      const kind = starts.length ? 'started' : 'completed'
      const latest = (starts.length ? starts : completions).at(-1)
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
