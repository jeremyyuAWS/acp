import { useEffect, useRef, useState } from 'react'

export default function WaterfallCount({ value, identity, paused = false, format = value => value.toLocaleString() }) {
  const previous = useRef(null)
  const [flash, setFlash] = useState(null)
  useEffect(() => {
    const before = previous.current
    previous.current = { value, identity }
    setFlash(null)
    if (paused || before?.identity !== identity || !Number.isSafeInteger(value) || !Number.isSafeInteger(before.value) || value === before.value) return undefined
    setFlash({ difference: value - before.value, identity })
    const timer = setTimeout(() => setFlash(null), 2600)
    return () => clearTimeout(timer)
  }, [value, identity, paused])
  return <span className="wf-count"><span>{Number.isSafeInteger(value) ? format(value) : 'Unavailable'}</span>{!paused && flash?.identity === identity && <span className="wf-delta" aria-hidden="true">{flash.difference > 0 ? '+' : '−'}{format(Math.abs(flash.difference))}</span>}</span>
}
