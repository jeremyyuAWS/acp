import { useEffect, useRef, useState } from 'react'
import { getRemediationSnapshot } from './api.js'
import { isNewer } from './remediationSnapshot.js'

// The run's live state, owned ABOVE the tab switch.
//
// WHY IT LIVES HERE AND NOT IN Remediate.jsx. App.jsx renders `<Remediate/>` only while
// `view === 'remediate'`, so everything that component owns — its poll, its stream, its
// denominator — is torn down the moment a user opens any other tab, and rebuilt from nothing when
// they come back. A run card that is supposed to survive tab changes therefore cannot be inside
// it; it has to be fed by state that outlives the panel.
//
// Deliberately does NOT open a second SSE connection. Remediate.jsx already holds one for the
// progress bar, and two streams per run would double the server's per-tick work to render one
// more card. This polls the reconciled snapshot — the same projection the stream carries — on a
// slow cadence, and reports its freshness honestly as polling rather than claiming "Live".
// Adopting the stream is a later step, and one that should MOVE ownership rather than add a
// second holder.
const ACTIVE_MS = 5000

export function useRemediationRun(runId) {
  const [snapshot, setSnapshot] = useState(null)
  const [receivedAt, setReceivedAt] = useState(null)
  const snapRef = useRef(null)

  useEffect(() => {
    // A different run is a different narrative. Clearing FIRST means the card can never show the
    // previous run's counters against the new run's id for even one paint.
    snapRef.current = null
    setSnapshot(null)
    setReceivedAt(null)
    if (!runId) return undefined

    let live = true
    const load = () => getRemediationSnapshot(runId)
      .then((next) => {
        if (!live || !next) return
        // Drop a snapshot whose revision went backwards — a superseded read arriving late would
        // otherwise walk the card's counters backwards, which reads as the run regressing.
        if (!isNewer(snapRef.current, next)) return
        snapRef.current = next
        setSnapshot(next)
        setReceivedAt(Date.now())
      })
      .catch(() => { /* transient: the last confirmed snapshot and its age stay on screen */ })

    load()
    // Terminality is read off the ref, not off `snapshot`: this interval closes over the state
    // from the render that created it, so `snapshot` here would be null forever and the
    // stop-when-terminal it expresses would never once be true.
    const id = setInterval(() => { if (!snapRef.current?.terminal) load() }, ACTIVE_MS)
    // Stops when the component unmounts — the brief's rule, and the reason this returns a
    // cleanup rather than relying on the run finishing.
    return () => { live = false; clearInterval(id) }
  }, [runId])

  return { snapshot, receivedAt }
}
