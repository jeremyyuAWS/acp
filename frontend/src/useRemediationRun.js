import { useCallback, useEffect, useRef, useState } from 'react'
import { getRemediationSnapshot, openRemediationStream, getRecentRemediationActivity } from './api.js'
import { isNewer } from './remediationSnapshot.js'
import { addRemediationEvent } from './remediationEventFeed.js'

// The run's live state, and THE ONE PLACE THAT HOLDS ITS STREAM.
//
// WHY OWNERSHIP LIVES HERE. App.jsx renders `<Remediate/>` only while `view === 'remediate'`, so a
// stream opened inside that component is closed the moment the user opens any other tab and
// reopened from scratch when they come back. Three things follow, and all three were true before
// this hook took the connection over:
//
//   * the persistent card could not say "Live" honestly — it polled, because opening a SECOND
//     stream to feed it would double the server's per-tick work for one card;
//   * ADR 0051's resume did nothing for a tab change. The cursor lived in Remediate's ref, so it
//     died with the component, and the reconnect replayed nothing because it had no cursor;
//   * a run went unwatched entirely while the user was on another tab.
//
// Now one stream outlives the tab switch, its cursor outlives it too, and a reconnect resumes
// from the last event this browser actually rendered — across tabs, not just across a dropped
// connection. Remediate.jsx consumes this rather than opening its own.
//
// THE POLL IS THE FALLBACK, NOT THE DEFAULT. The stream closes itself once the run is finished —
// terminal AND with no corrected copy still awaiting delivery (routes/scans.py's
// `_stream_is_finished`; it used to end on `in_flight == 0`, which closed while delivery and
// final reconciliation were still outstanding). An idle or finished run has no stream at all, so
// the snapshot is fetched once up front and then polled only while nothing is streaming.
const IDLE_POLL_MS = 5000
const RECONNECT_MS = 3000

export function useRemediationRun(runId) {
  const [snapshot, setSnapshot] = useState(null)
  const [receivedAt, setReceivedAt] = useState(null)
  const [connected, setConnected] = useState(false)
  // The most recent legacy status frame. Remediate's progress bar is driven from this rather
  // than from its own stream — one connection, two consumers.
  const [status, setStatus] = useState(null)
  // Bumped when the server closes the stream cleanly. Remediate watches it to finalize its batch;
  // a counter rather than a boolean so a second run's completion is distinguishable from the
  // first's still being set.
  const [endedAt, setEndedAt] = useState(0)
  // A bounded projection of durable lifecycle events. State remains server-owned in `snapshot`;
  // these rows answer the different question "what just happened?" and survive tab changes with
  // the stream because this hook lives at App level.
  const [events, setEvents] = useState([])
  const [activityStatus, setActivityStatus] = useState('loading')

  const snapRef = useRef(null)
  const streamRef = useRef(null)
  const pollRef = useRef(null)
  const reconnectRef = useRef(null)
  // The resume cursor: the last scan_events.seq this browser actually rendered (ADR 0051). A ref,
  // not state, because the NEXT connect attempt must read it without waiting for a render.
  const cursorRef = useRef(null)

  const accept = useCallback((next) => {
    if (!next) return
    // Drop a snapshot whose revision went backwards — a superseded read arriving late would walk
    // the counters backwards, which reads as the run regressing.
    if (!isNewer(snapRef.current, next)) return
    snapRef.current = next
    setSnapshot(next)
    setReceivedAt(Date.now())
  }, [])

  useEffect(() => {
    // A different run is a different narrative AND a different event log. Clearing the cursor
    // matters as much as clearing the snapshot: carrying one across runs would ask the server to
    // resume run B from run A's position, which it would (correctly) refuse as a cursor ahead of
    // the log — a reconcile on every first connect.
    snapRef.current = null
    cursorRef.current = null
    setSnapshot(null); setReceivedAt(null); setStatus(null); setConnected(false); setEvents([]); setActivityStatus('loading')
    if (!runId) return undefined

    let live = true
    const stopPoll = () => { clearInterval(pollRef.current); pollRef.current = null }
    const stopReconnect = () => { clearTimeout(reconnectRef.current); reconnectRef.current = null }
    const stopForExpiredSession = () => {
      // App keeps this hook mounted while it swaps the signed-in shell for SignIn. Without this,
      // the fallback interval sends the rejected request every five seconds until reload/login.
      live = false
      stopPoll()
      stopReconnect()
      streamRef.current?.close?.()
      streamRef.current = null
      setConnected(false)
    }
    window.addEventListener('acp:session-expired', stopForExpiredSession)

    let streamNeedsSnapshot = false
    let snapshotPending = false
    const loadSnapshot = async () => {
      if (!live || snapshotPending) return
      snapshotPending = true
      try {
        const next = await getRemediationSnapshot(runId)
        if (live) accept(next)
      } catch (error) {
        if (!live) return
        if ([401, 403, 404].includes(error?.status)) {
          // An inaccessible/removed scan is not a transport gap. Stop retrying it and
          // discard scoped progress; never fall back to another owner's scan.
          stopForExpiredSession()
          snapRef.current = null
          setSnapshot(null); setReceivedAt(null); setStatus(null); setEvents([])
          setActivityStatus('unavailable')
        } else {
          // Retain confirmed totals during transient errors and recover even if the
          // stream is producing legacy status frames without a reconciled snapshot.
          startPoll()
        }
      } finally { snapshotPending = false }
    }

    let historyPending = false, historyAgain = false
    const loadHistory = async () => {
      if (!live) return
      if (historyPending) { historyAgain = true; return }
      historyPending = true
      try {
        const result = await getRecentRemediationActivity(runId)
        if (!live) return
        if (result?.available !== true || !Array.isArray(result.events)) throw new Error('History unavailable')
        setEvents(previous => result.events.reduce((rows, event) => addRemediationEvent(rows, event, event.seq), previous))
        setActivityStatus('ready')
      } catch { if (live) setActivityStatus('unavailable') }
      finally {
        historyPending = false
        if (live && historyAgain) { historyAgain = false; loadHistory() }
      }
    }

    const startPoll = () => {
      if (!live || pollRef.current) return
      pollRef.current = setInterval(() => {
        // Terminality is read off the REF: this closure captures state from the render that
        // created it, so `snapshot` here would be null forever and the stop-when-terminal it
        // expresses would never once be true.
        if (!snapRef.current?.terminal || streamNeedsSnapshot) { loadSnapshot(); loadHistory() }
      }, IDLE_POLL_MS)
    }

    const connect = () => {
      if (!live) return
      stopReconnect()
      streamRef.current?.close?.()
      streamRef.current = openRemediationStream(runId, {
        lastEventId: cursorRef.current,
        onMessage: (frame) => {
          if (!live) return
          setConnected(true)
          if (frame?.snapshot) {
            streamNeedsSnapshot = false
            stopPoll()                       // a reconciled frame supersedes the fallback
            if (isNewer(snapRef.current, frame.snapshot)) setStatus(frame)
            accept(frame.snapshot)
          } else {
            streamNeedsSnapshot = true
            setStatus(frame)
            startPoll()                      // transport alone cannot refresh reconciled totals
          }
        },
        onEvent: (event, id) => {
          if (!live) return
          // The FRAME's id is the authority, not a field inside the payload: the cursor must only
          // ever advance to something this client actually rendered.
          if (id != null) cursorRef.current = id
          setEvents((previous) => addRemediationEvent(previous, event, id))
        },
        onReconcile: () => {
          // The server declined to replay — cursor ahead of the log, log pruned, cursor malformed.
          // Drop it and re-fetch a snapshot BEFORE applying anything later (PRD §17.6); keeping a
          // cursor the server has rejected would fail identically on every later reconnect.
          cursorRef.current = null
          loadSnapshot()
          loadHistory()
        },
        onDone: () => {
          if (!live) return
          streamNeedsSnapshot = false
          setConnected(false)
          setEndedAt(Date.now())
          loadHistory()
          // `done` is stronger than it was — the server holds the stream through delivery now —
          // and the poll still starts, deliberately: review and evidence can outlive delivery,
          // and the reconciled snapshot, not one frame, is what says the run is terminal.
          startPoll()
        },
        onError: () => {
          if (!live) return
          streamRef.current = null
          loadHistory()
          setConnected(false)
          startPoll()
          // A stream error is a transport interruption, not a terminal run state. Keep the
          // reconciled snapshot poll alive while retrying one connection at a time; the durable
          // cursor makes a successful reconnect replay every lifecycle event missed meanwhile.
          if (!snapRef.current?.terminal && !reconnectRef.current) {
            reconnectRef.current = setTimeout(connect, RECONNECT_MS)
          }
        },
      })
    }

    loadSnapshot()   // so an idle or finished run has state even with no stream to open
    loadHistory() // A first stream starts at the latest cursor; restore saved narration separately.
    connect()
    return () => {
      live = false
      window.removeEventListener('acp:session-expired', stopForExpiredSession)
      stopPoll()
      stopReconnect()
      streamRef.current?.close?.()
      streamRef.current = null
    }
  }, [runId, accept])

  return { snapshot, receivedAt, connected, status, endedAt, events, activityStatus }
}
