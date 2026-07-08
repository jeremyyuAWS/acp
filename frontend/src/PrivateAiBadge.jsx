import { useState, useEffect } from 'react'
import { getAiStatus } from './api.js'

// A trust badge for the security story: ACP's AI runs on a self-hosted local model
// (Ollama) — no document content ever leaves the deployment for a third-party AI. We
// only render it when the live backend actually reports `ollama`, so it's a true claim,
// never decoration. Silent when AI is off or the backend isn't local.
export default function PrivateAiBadge({ aiEnabled }) {
  const [st, setSt] = useState(null)

  useEffect(() => {
    let alive = true
    getAiStatus().then((s) => { if (alive) setSt(s) }).catch(() => { if (alive) setSt(null) })
    return () => { alive = false }
  }, [])

  if (!aiEnabled || !st || st.backend !== 'ollama') return null
  return (
    <span
      className="privai"
      title={`Private AI — all inference runs on a self-hosted local model${st.model ? ` (${st.model})` : ''}. `
        + 'No document content leaves your environment; no OpenAI/Anthropic, no external tokens.'}>
      🔒 Private AI · local
    </span>
  )
}
