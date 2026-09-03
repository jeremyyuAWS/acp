import { useEffect, useState } from 'react'
import { getLifecycleSummary } from './api.js'
import LifecycleEstateSummary from './LifecycleEstateSummary.jsx'

export default function DiscoveryLifecycleEstateSummary({ scanId }) {
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let current = true
    setSummary(null)
    setError('')
    if (!scanId) return () => { current = false }
    getLifecycleSummary(scanId)
      .then((value) => { if (current) setSummary(value) })
      .catch(() => { if (current) setError('The lifecycle estate summary could not be loaded.') })
    return () => { current = false }
  }, [scanId])

  if (error) return <p role="alert">{error}</p>
  return summary ? <LifecycleEstateSummary summary={summary} /> : null
}
