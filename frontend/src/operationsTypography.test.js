import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, 'operations-typography.css'), 'utf8')
const analytics = readFileSync(join(here, 'AdminInsights.jsx'), 'utf8')
const liveOps = readFileSync(join(here, 'AdminLiveTraffic.jsx'), 'utf8')

describe('shared operations typography', () => {
  it('gives analytics and Live Operations the same KPI hierarchy and width', () => {
    expect(analytics).toContain("import './operations-typography.css'")
    expect(liveOps).toContain("import './operations-typography.css'")
    expect(analytics).toContain('className="ops-kpi-grid ops-kpi-grid--analytics"')
    expect(liveOps).toContain('className="ops-kpi-grid"')
    expect(css).toMatch(/minmax\(180px, 1fr\)/)
    expect(css).toMatch(/\.ops-kpi__value\s*\{[^}]*font-family:\s*inherit/s)
    expect(css).toMatch(/\.ops-kpi__value\s*\{[^}]*font-size:\s*24px/s)
    expect(css).toMatch(/\.ops-kpi__label\s*\{[^}]*font-size:\s*12px/s)
  })

  it('does not regress the KPI cards to scattered inline font declarations', () => {
    expect(analytics).not.toMatch(/fontSize:\s*26,\s*fontWeight:\s*700/)
    for (const label of ['WORKER CAPACITY', 'SHARED QUEUE', 'UTILIZATION', 'CANONICAL DELIVERY']) {
      expect(liveOps).toContain(label)
    }
    expect(liveOps).not.toMatch(/<b style=\{\{ fontSize: 20 \}\}/)
  })
})
