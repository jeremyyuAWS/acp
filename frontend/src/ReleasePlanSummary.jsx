const methodLabel = (method, provider) => method === 'publish'
  ? `Publish to ${provider || 'connected source'}`
  : method === 'download' ? 'Download ZIP' : 'Keep in ACP'

export function formatReleaseBytes(value) {
  if (!Number.isFinite(value) || value < 0) return 'Size calculated before delivery'
  if (value < 1024) return `${value} B`
  const units = ['KB', 'MB', 'GB']
  let amount = value / 1024
  let unit = units[0]
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024
    unit = units[index]
  }
  return `${amount >= 10 ? amount.toFixed(0) : amount.toFixed(1)} ${unit}`
}

export default function ReleasePlanSummary({ count = 0, excluded = 0, method = 'publish',
  provider, destination, preserveStructure = true, estimatedBytes, compact = false }) {
  return (
    <aside className={`release-plan-summary${compact ? ' release-plan-summary--compact' : ''}`}
           aria-label="Current release plan">
      <div className="release-plan-summary__heading">
        <b>Your release plan</b>
        <span>{count} selected</span>
      </div>
      <dl>
        <dt>Delivery</dt><dd>{methodLabel(method, provider)}</dd>
        <dt>Destination</dt><dd>{method === 'publish' ? destination || 'Choose a destination'
          : method === 'download' ? 'This device' : 'ACP controlled storage'}</dd>
        <dt>Folders</dt><dd>{preserveStructure ? 'Preserve source structure' : 'Place files together'}</dd>
        <dt>Output size</dt><dd>{formatReleaseBytes(estimatedBytes)}</dd>
      </dl>
      <div className="release-plan-summary__safety">Original files stay unchanged</div>
      {excluded > 0 && <div className="release-plan-summary__excluded">{excluded} excluded for safety or review</div>}
    </aside>
  )
}
