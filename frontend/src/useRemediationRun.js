import { useCallback, useEffect, useRef, useState } from 'react'
import { getRemediationSnapshot, openRemediationStream } from './api.js'
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
// THE POLL IS THE FALLBACK, NOT THE DEFAULT. The stream closes itself when the batch drains
// (routes/scans.py ends it on `in_flight == 0`), and an idle or finished run has no stream at
// all — so the snapshot is fetched once up front and then polled only while nothing is streaming.
const IDLE_POLL_MS = 5000

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

  const snapRef = useRef(null)
  const streamRef = useRef(null)
  const pollRef = useRef(null)
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
    setSnapshot(null); setReceivedAt(null); setStatus(null); setConnected(false); setEvents([])
    if (!runId) return undefined

    let live = true
    const stopPoll = () => { clearInterval(pollRef.current); pollRef.current = null }
    const stopForExpiredSession = () => {
      // App keeps this hook mounted while it swaps the signed-in shell for SignIn. Without this,
      // the fallback interval sends the rejected request every five seconds until reload/login.
      live = false
      stopPoll()
      streamRef.current?.close?.()
      streamRef.current = null
      setConnected(false)
    }
    window.addEventListener('acp:session-expired', stopForExpiredSession)

    const loadSnapshot = () => getRemediationSnapshot(runId)
      .then((next) => { if (live) accept(next) })
      .catch(() => { /* transient: the last confirmed snapshot and its age stay on screen */ })

    const startPoll = () => {
      if (!live || pollRef.current) return
      pollRef.current = setInterval(() => {
        // Terminality is read off the REF: this closure captures state from the render that
        // created it, so `snapshot` here would be null forever and the stop-when-terminal it
        // expresses would never once be true.
        if (!snapRef.current?.terminal) loadSnapshot()
      }, IDLE_POLL_MS)
    }

    const connect = () => {
      if (!live) return
      streamRef.current?.close?.()
      streamRef.current = openRemediationStream(runId, {
        lastEventId: cursorRef.current,
        onMessage: (frame) => {
          if (!live) return
          setConnected(true)
          stopPoll()                       // a live frame supersedes the fallback
          setStatus(frame)
          accept(frame?.snapshot)
        },
        onEvent: (event, id) => {
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
        },
        onDone: () => {
          if (!live) return
          setConnected(false)
          setEndedAt(Date.now())
          // The batch drained, but review, delivery and evidence may not have. Poll on so the
          // card keeps reconciling until the SNAPSHOT says the run is terminal — the stream's
          // own close is about in-flight jobs, not about the run being finished.
          startPoll()
        },
        onError: () => {
          if (!live) return
          streamRef.current = null
          setConnected(false)
          startPoll()
        },
      })
    }

    loadSnapshot()   // so an idle or finished run has state even with no stream to open
    connect()
    return () => {
      live = false
      window.removeEventListener('acp:session-expired', stopForExpiredSession)
      stopPoll()
      streamRef.current?.close?.()
      streamRef.current = null
    }
  }, [runId, accept])

  return { snapshot, receivedAt, connected, status, endedAt, events }
}
