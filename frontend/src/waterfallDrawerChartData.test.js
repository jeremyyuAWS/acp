import { describe, it, expect } from 'vitest'
import { buildWaterfallDrawerCharts } from './waterfallDrawerChartData'
describe('drawer chart contract', () => {
  it('never invents unknown costs or rates', () => {
    const data = buildWaterfallDrawerCharts()
    expect(data.pace.value).toBeNull()
    expect(data.spend.total).toBeNull()
    expect(data.spend.complete).toBe(false)
  })
  it('preserves server gaps and explicit zero', () => {
    const metrics = { contract_version: 'waterfall-drawer-metrics.v1', pace: { value: 0 }, trend: { points: [{ value: null }] }, contribution: { rows: [] }, spend: { total: 0, complete: true } }
    expect(buildWaterfallDrawerCharts({ metrics })).toEqual({ pace: metrics.pace, trend: metrics.trend, contribution: metrics.contribution, spend: metrics.spend })
  })
})
