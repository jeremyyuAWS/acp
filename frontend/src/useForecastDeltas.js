import { useEffect, useRef, useState } from 'react'

// Compare settled selections, never active defaults, loading placeholders or another scope.
export default function useForecastDeltas({ identity, ready, policyKey, automatic, human }) {
  const previous = useRef(null)
  const scope = useRef(identity)
  const [flash, setFlash] = useState(null)
  useEffect(() => {
    if (scope.current !== identity) {
      scope.current = identity
      previous.current = null
      setFlash(null)
      // A new scope may already have its settled result: baseline it in this effect.
    }
    if (!ready) return
    const before = previous.current
    previous.current = { policyKey, automatic, human }
    if (!before || before.policyKey === policyKey) return
    const valid = value => Number.isSafeInteger(value) && value >= 0
    const difference = (now, old) => valid(now) && valid(old) ? now - old : 0
    const values = { automatic: difference(automatic, before.automatic), human: difference(human, before.human) }
    setFlash(values.automatic || values.human ? { identity, policyKey, values } : null)
  }, [identity, ready, policyKey, automatic, human])
  // The badge owns its lifetime. Background result refreshes must not cancel or restart it.
  useEffect(() => {
    if (!flash) return undefined
    const timer = setTimeout(() => setFlash(null), 2600)
    return () => clearTimeout(timer)
  }, [flash])
  return ready && flash && flash.identity === identity && flash.policyKey === policyKey ? flash.values : null
}
