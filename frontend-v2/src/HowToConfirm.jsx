import { useState } from 'react'
import { verifySteps, defaultPlatform } from './verifySteps.js'

// The third piece of the HITL card, beside the thumbnail and the AI-suggested value: exactly
// where the reviewer clicks in the native app (Word/Excel/PowerPoint/Acrobat, macOS vs Windows)
// to confirm the fix actually took. Renders nothing when we have no honest steps for the
// (criterion, app) — never a wrong instruction.
export default function HowToConfirm({ sc, file }) {
  const [platform, setPlatform] = useState(defaultPlatform())
  const info = verifySteps(sc, file, platform)
  if (!info) return null

  const seg = (p, label) => (
    <button
      type="button"
      className={platform === p ? 'seg on' : 'seg'}
      aria-pressed={platform === p}
      onClick={(e) => { e.preventDefault(); setPlatform(p) }}
      style={{ fontSize: 12, padding: '2px 10px' }}
    >{label}</button>
  )

  return (
    <details className="howto" style={{ marginTop: 12 }}>
      <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13 }}>
        How to confirm this fix in {info.app}
      </summary>
      <div style={{ marginTop: 8 }}>
        <div role="group" aria-label="Platform" style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          {seg('mac', 'macOS')}
          {seg('win', 'Windows')}
        </div>
        {info.steps ? (
          <ol style={{ margin: '0 0 8px 18px', fontSize: 12.5, lineHeight: 1.5 }}>
            {info.steps.map((s, i) => <li key={i}>{s}</li>)}
          </ol>
        ) : (
          <p className="muted" style={{ fontSize: 12.5, margin: '0 0 8px' }}>
            {info.app} has no one-click check for this one — confirm with the built-in checker:
          </p>
        )}
        {info.checker && (
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            Re-run the checker: <b>{info.checker}</b>
          </p>
        )}
      </div>
    </details>
  )
}
