import { chartPercent } from './BreakdownBars.jsx'

const GROUPS = [
  ['assessable', 'Eligible for assessment', '#28784b'],
  ['metadata_only', 'Metadata only', '#477ab6'],
  ['unsupported', 'Unsupported formats', '#737581'],
  ['excluded', 'Excluded', '#9b6085'],
]

export default function DiscoveryPopulationChart({ inventory }) {
  const total = inventory?.discovered
  const valid = n => Number.isSafeInteger(n) && n >= 0
  if (!valid(total) || !inventory?.by_status) return null
  const groups = GROUPS.map(([key,label,color]) => ({key,label,color,count:inventory.by_status[key] ?? 0}))
  if (!groups.every(g=>valid(g.count))) return null
  const sum = groups.reduce((n,g)=>n+g.count,0)
  const balanced = sum <= total
  if (sum < total) groups.push({key:'unknown',label:'Not classified',color:'#aa751a',count:total-sum})
  let offset = 0
  return <section className="panel" aria-label="All source files" style={{marginTop:16}}>
    <h2>ALL SOURCE FILES</h2>
    <p className="muted" style={{fontSize:13}}>Base: {total.toLocaleString()} files found at the source, including excluded files{inventory.truncated ? ' · partial listing' : ''}.</p>
    {!balanced ? <p role="status">Category counts exceed the source total. This chart is unavailable until counts reconcile.</p> : <div style={{display:'flex',alignItems:'center',gap:28,flexWrap:'wrap'}}>
      <svg viewBox="0 0 220 220" width="220" height="220" role="img" aria-label={`${total.toLocaleString()} source files. ${groups.map(g=>`${g.label}: ${g.count.toLocaleString()}`).join('. ')}`} style={{flex:'0 0 220px'}}>
        <circle cx="110" cy="110" r="82" fill="none" stroke="var(--line)" strokeWidth="28" />
        {total > 0 && groups.filter(g=>g.count>0).map(g=>{
          const length = g.count / total * 100
          const start = offset; offset += length
          return <circle key={g.key} cx="110" cy="110" r="82" pathLength="100" fill="none" stroke={g.color} strokeWidth="28"
            strokeDasharray={`${length} ${100-length}`} strokeDashoffset={-start} transform="rotate(-90 110 110)" />
        })}
        <text x="110" y="108" textAnchor="middle" fill="currentColor" fontSize="27" fontWeight="700">{total.toLocaleString()}</text>
        <text x="110" y="130" textAnchor="middle" fill="currentColor" fontSize="12">source files</text>
      </svg>
      <div style={{flex:'1 1 260px'}}>
        <ul style={{listStyle:'none',padding:0,margin:0}}>{groups.map(g=><li key={g.key} style={{display:'flex',alignItems:'center',gap:10,padding:'8px 0',borderBottom:'1px solid var(--line)'}}>
          <span aria-hidden="true" style={{width:12,height:12,borderRadius:3,background:g.color,flexShrink:0}} />
          <span style={{flex:1}}>{g.label}</span><strong>{g.count.toLocaleString()}</strong><span className="muted" style={{minWidth:55,textAlign:'right'}}>{chartPercent(g.count,total)}%</span>
        </li>)}</ul>
        <p className="muted" style={{fontSize:12}}>{groups.map(g=>g.count.toLocaleString()).join(' + ')} = {total.toLocaleString()} source files. Percentages are rounded. Excluded files remain visible here but are not assessed again.</p>
      </div>
    </div>}
  </section>
}
