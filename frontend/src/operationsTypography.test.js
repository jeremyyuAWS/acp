import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = dirname(fileURLToPath(import.meta.url))
const css = readFileSync(join(here, 'operations-typography.css'), 'utf8')
const analytics = readFileSync(join(here, 'AdminInsights.jsx'), 'utf8')
const liveCss = readFileSync(join(here, 'liveops-typography.css'), 'utf8')
const liveOps = readFileSync(join(here, 'AdminLiveTraffic.jsx'), 'utf8')

describe('shared operations typography', () => {
  it('gives analytics and Live Operations the same KPI hierarchy and width', () => {
    expect(analytics).toContain("import './operations-typography.css'")
    expect(liveOps).toContain("import './operations-typography.css'")
    expect(analytics).toContain('className="ops-kpi-grid ops-kpi-grid--analytics"')
    expect(liveOps).toContain('className="ops-kpi-grid"')
    expect(css).toMatch(/minmax\(180px, 1fr\)/)
    expect(css).toMatch(/\.ops-kpi__value\s*\{[^}]*font-family:\s*inherit/s)
    expect(css).toMatch(/\.ops-kpi__value\s*\{[^}]*font-size:\s*var\(--text-metric, 24px\)/s)
    expect(css).toMatch(/\.ops-kpi__label\s*\{[^}]*font-size:\s*var\(--text-small, 12px\)/s)
  })

  it('uses explicit numeric values rather than card position for mono', () => {
    expect(liveCss).not.toContain('nth-child')
    expect(liveCss).toMatch(/\.liveops-theme \.ops-kpi__value,[^}]*liveops-infra__value\s*\{[^}]*font-size:\s*var\(--liveops-tile-value\)/s)
    expect(liveCss).toContain('--liveops-tile-value: 17px')
    expect(liveCss).toMatch(/ops-kpi__value \.machine-value[^}]*font-family:var\(--font-ui\)/)
    expect(liveOps).toContain('className="liveops-infra__value"')
    expect(liveCss).toMatch(/:is\(b, strong, h2, h3, h4, summary, button, th\)\s*\{[^}]*font-weight:\s*600/s)
    expect(css).toMatch(/\.ops-kpi__value \.machine-value\s*\{[^}]*font-size:\s*inherit/s)
  })

  it('does not regress the KPI cards to scattered inline font declarations', () => {
    expect(analytics).not.toMatch(/fontSize:\s*26,\s*fontWeight:\s*700/)
    for (const label of ['WORKER CAPACITY', 'SHARED QUEUE', 'UTILIZATION', 'CANONICAL DELIVERY']) {
      expect(liveOps).toContain(label)
    }
    expect(liveOps).not.toMatch(/<b style=\{\{ fontSize: 20 \}\}/)
  })
})

it('keeps Live Azure summary and infrastructure tiles on the same value, label and metadata roles', () => {
  for (const role of ['value','label','meta']) {
    expect(liveCss).toContain(`.liveops-theme .liveops-infra__${role}`)
    expect(liveOps).toContain(`className="liveops-infra__${role}"`)
  }
  expect(liveCss).toContain('--liveops-tile-label: 10.5px')
  expect(liveCss).toContain('--liveops-tile-meta: 11px')
  expect(css).toContain('font-size: var(--text-metric, 24px)') // analytics remains unchanged
})
