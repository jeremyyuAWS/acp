import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationThroughput, { remediationThroughputPoints } from './RemediationThroughput.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(async () => unmountAll())

it('converts measured buckets into cumulative progress without inventing movement', () => {
  expect(remediationThroughputPoints([0, 0, 2, 0])).toEqual([0, 0, 0, 2, 2])
  expect(remediationThroughputPoints([0, 0])).toEqual([0, 0, 0])
  expect(remediationThroughputPoints(Array(12).fill(1))).toHaveLength(11)
  for (const invalid of [undefined, [], [0, null], [1, -1], [1, NaN], [1, '2']]) {
    expect(remediationThroughputPoints(invalid)).toEqual([])
  }
})

it('uses the compact stage chart and labels its real time buckets', () => {
  const html = renderToStaticMarkup(<RemediationThroughput identity="run"
    data={{ buckets: [0, 2, 0], documents_per_minute: 0.4 }} />)
  expect(html).toContain('width="220"')
  expect(html).toContain('height="42"')
  expect(html).toContain('<polyline')
  expect(html).toContain('0.4 documents/min')
  expect(html).toContain('processed count moved from 0 to 2 across 4 time points')
  expect(html).not.toContain('live updates')
})

it('keeps the header small and omits unknown or insufficient trends', () => {
  const html = renderToStaticMarkup(<RemediationThroughput mini identity="run"
    data={{ buckets: [0, 2, 0], documents_per_minute: 0.4 }} />)
  expect(html).toContain('width="92"')
  expect(html).toContain('height="20"')
  for (const data of [{ buckets: [], documents_per_minute: 0.4 }, { buckets: [1], documents_per_minute: null }]) {
    expect(renderToStaticMarkup(<RemediationThroughput mini identity="run" data={data} />)).toBe('')
  }
})

it('freezes visual updates while paused and never carries a previous run into a new one', async () => {
  const { root, container } = createTestRoot()
  const render = (rate, paused, identity = 'first') => act(async () => root.render(
    <RemediationThroughput mini identity={identity} paused={paused}
      data={{ buckets: [0, rate], documents_per_minute: rate }} />))
  await render(1, false)
  await render(2, true)
  expect(container.textContent).toContain('1 documents/min')
  await render(2, false)
  expect(container.textContent).toContain('2 documents/min')
  await render(3, true, 'next')
  expect(container.textContent).toContain('3 documents/min')
})
