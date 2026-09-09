/** Charts consume server aggregates, never infer whole-run totals from paged attempts. */
export function buildWaterfallDrawerCharts({ metrics } = {}) {
  if (metrics?.contract_version === 'waterfall-drawer-metrics.v1') {
    const { pace, trend, contribution, spend } = metrics
    return { pace, trend, contribution, spend }
  }
  const reason = 'Recorded chart metrics are unavailable.'
  return {
    pace: { value: null, unit: 'recorded completions/min', windowLabel: 'Last 60 seconds', observedSeconds: 0, reason },
    trend: { unit: 'recorded completions/min', windowLabel: 'Last 10 minutes', bucketLabel: '60-second buckets', timeZone: 'UTC', points: [], reason },
    contribution: { title: 'Recorded attempt outcomes', unit: 'attempts', basis: 'Recorded validation outcomes', rows: [], reason },
    spend: { unit: null, complete: false, partition: false, total: null, rows: [], reason },
  }
}
