// Compact heatmap for the chat (e.g. department × severity). Cells shade by value.
export default function Heatmap({ rows, cols, matrix }) {
  const max = Math.max(1, ...matrix.flat())
  return (
    <table className="heatmap">
      <thead><tr><th aria-hidden="true" />{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, ri) => (
          <tr key={r}>
            <td className="hmrow">{r}</td>
            {cols.map((c, ci) => {
              const v = matrix[ri][ci]; const a = v / max
              return <td key={c} className="hmcell" style={{ background: v ? `rgba(226,75,74,${(0.14 + a * 0.76).toFixed(2)})` : '#f4f1f5', color: a > 0.55 ? '#fff' : '#7a7280' }} title={`${r} · ${c}: ${v}`}>{v || ''}</td>
            })}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
