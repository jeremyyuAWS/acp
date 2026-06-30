import { useState, useEffect } from 'react'
import { getDigest } from './api.js'

// AI Compliance Digest (bundle #2) — an executive paragraph written by the model, grounded
// strictly in the real scan numbers (score, regressions, top systemic issue), with the
// factual bullets shown alongside so nothing is taken on trust. Falls back to a deterministic
// paragraph when the model is off/unavailable (the backend handles that).
export default function ComplianceDigest({ run }) {
  const [digest, setDigest] = useState(null)
  const [loading, setLoading] = useState(false)
  const runId = run?.id

  const load = (refresh = false) => {
    if (!runId) return
    setLoading(true)
    getDigest(runId, refresh)
      .then((d) => setDigest(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }
  useEffect(() => { setDigest(null); if (runId) load(false) }, [runId]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!runId) return null
  return (
    <section className="panel digestpanel" style={{ marginBottom: 14 }}>
      <div className="proghd">
        <h2 style={{ margin: 0 }}>✦ Compliance digest <span className="muted" style={{ fontSize: 12 }}>· {digest?.ai ? 'AI-written from your real scan data' : 'from your real scan data'}</span></h2>
        <button className="ghost small" onClick={() => load(true)} disabled={loading}>{loading ? 'Generating…' : '↻ Regenerate'}</button>
      </div>

      {loading && !digest ? (
        <p className="muted" style={{ marginTop: 12 }}><span className="spinner" style={{ display: 'inline-block', verticalAlign: 'middle', marginRight: 8 }} />Analysing your estate…</p>
      ) : digest ? (
        <>
          <p className="digestnarr">{digest.narrative}</p>
          {digest.changed?.length > 0 && (
            <ul className="digestchanged">
              {digest.changed.map((c, i) => <li key={i}>{c}</li>)}
            </ul>
          )}
          <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
            {digest.ai ? `Narrative by ${digest.model}` : 'Deterministic summary (AI unavailable)'} · every figure is from your scan — nothing invented.
          </p>
        </>
      ) : null}
    </section>
  )
}
