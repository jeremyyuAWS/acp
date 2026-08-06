import { Bars, Donut } from './charts.jsx'
import { Sparkline } from './ScoreRing.jsx'
import Heatmap from './Heatmap.jsx'

// Renders an inline chart inside a chat answer. The router (ChatWidget) decides
// the type + data; this just maps it to the right small visual.
export default function ChatChart({ chart }) {
  if (!chart) return null
  return (
    <div className="chatchart">
      {chart.type === 'bar' && <Bars items={chart.data} cols={chart.gridCols || '120px 1fr 26px'} />}
      {chart.type === 'donut' && <Donut segments={chart.data} size={112} thickness={15} caption={chart.caption || 'docs'} />}
      {chart.type === 'line' && <Sparkline points={chart.points} labels={chart.labels} width={chart.width || 300} height={96} />}
      {chart.type === 'heatmap' && <Heatmap rows={chart.rows} cols={chart.cols} matrix={chart.matrix} />}
    </div>
  )
}
