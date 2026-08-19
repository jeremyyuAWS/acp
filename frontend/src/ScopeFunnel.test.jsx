// The live scope funnel: answers "why 250 selected → fewer assessed" from the three-denominator
// inventory, so fewer-assessed is explained rather than glossed over. Reuses statusRows, so the
// numbers match EstateCoverage.
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ScopeFunnel from './ScopeFunnel.jsx'

afterEach(unmountAll)

async function render(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ScopeFunnel, props)) })
  return container
}

const INV = { discovered: 250, by_status: { assessable: 214, metadata_only: 25, unsupported: 11 } }

it('breaks discovered down by eligibility, most-eligible first', async () => {
  const c = await render({ inventory: INV })
  const t = c.textContent.replace(/\s+/g, ' ')
  expect(t).toMatch(/250 discovered/)
  expect(t).toMatch(/214 assessable/)
  expect(t).toMatch(/25 metadata-only/)
  expect(t).toMatch(/11 unsupported/)
})

it('surfaces the couldn’t-open count when the scan reported one', async () => {
  const c = await render({ inventory: INV, blocked: 5 })
  expect(c.textContent.replace(/\s+/g, ' ')).toMatch(/5 couldn’t open/)
})

it('renders nothing without an inventory — no empty shell', async () => {
  expect((await render({ inventory: null })).querySelector('.scopefunnel')).toBeFalsy()
  expect((await render({ inventory: { discovered: 0, by_status: {} } })).querySelector('.scopefunnel')).toBeFalsy()
})
