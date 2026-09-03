import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LiveThroughput from './LiveThroughput.jsx'

describe('LiveThroughput', () => {
  it('renders measured samples and an accessible rate', () => {
    const html = renderToStaticMarkup(
      <LiveThroughput points={[2, 4, 9, 12]} ratePerMin={18} label="Assessment throughput" />,
    )
    expect(html).toContain('<polyline')
    expect(html).toContain('18 documents/min')
    expect(html).toContain('completed count moved from 2 to 12')
    expect(html).toContain('2 → 12 completed · 4 live updates')
    expect(html).toContain('Earlier')
    expect(html).toContain('Now')
  })

  it('says it is calibrating rather than inventing a line from one sample', () => {
    const html = renderToStaticMarkup(<LiveThroughput points={[2]} label="Fix throughput" />)
    expect(html).toContain('Fix throughput · calibrating')
    expect(html).not.toContain('<svg')
  })
})
