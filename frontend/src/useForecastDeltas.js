import { useEffect, useRef, useState } from 'react'

// Compare settled selections, never active defaults, loading placeholders or another scope.
export default function useForecastDeltas({ identity, ready, policyKey, automatic, human }) {
  const previous = useRef(null)
  const scope = useRef(identity)
  const [flash, setFlash] = useState(null)
  useEffect(() => {
    setFlash(null)
    if (scope.current !== identity) {
      scope.current = identity
      previous.current = null
      return
    }
    if (!ready) return
    const before = previous.current
    previous.current = { policyKey, automatic, human }
    if (!before || before.policyKey === policyKey) return
    const difference = (now, old) => Number.isFinite(now) && Number.isFinite(old) ? now - old : 0
    const next = { automatic: difference(automatic, before.automatic), human: difference(human, before.human) }
    if (!next.automatic && !next.human) return
    setFlash(next)
    const timer = setTimeout(() => setFlash(null), 2600)
    return () => clearTimeout(timer)
  }, [identity, ready, policyKey, automatic, human])
  return ready ? flash : null
}
