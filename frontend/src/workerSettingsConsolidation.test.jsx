import { describe, it, expect, vi, afterEach } from 'vitest'
import { act } from 'react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
const state = vi.hoisted(() => ({ applied: false }))
vi.mock('./api.js', () => ({ getCapacitySchedule: () => Promise.resolve({ enabled: false, applied: state.applied, timezone: 'UTC', days: [], business_hours: {}, off_hours: {}, maximums: {} }) }))
vi.mock('./WorkerReplicaControl.jsx', () => ({ default: ({ me }) => <button disabled={!me?.is_admin}>Manual worker control</button> }))
import CapacitySchedule from './CapacitySchedule.jsx'
afterEach(unmountAll)
async function mount(admin, applied = false) {
  state.applied = applied
  const { root, container } = createTestRoot()
  await act(async () => root.render(<CapacitySchedule me={{ is_admin: admin }} />))
  return container
}
describe('one capacity settings surface', () => {
  it('retains the legacy component without mounting its retired Settings panel', () => {
    const settings = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'Settings.jsx'), 'utf8')
    expect(settings).toContain('function WorkerConfiguration(')
    expect(settings).not.toContain('<WorkerConfiguration')
    expect(settings).not.toContain('>Worker Configuration</button>')
  })
  it('keeps the pre-schedule manual adjustment collapsed until requested', async () => {
    const c = await mount(true)
    const summary = [...c.querySelectorAll('summary')].find((s) => s.textContent === 'Adjust current worker capacity')
    expect(summary.parentElement.open).toBe(false)
    expect(c.textContent).not.toContain('Manual worker control')
    await act(async () => { summary.parentElement.open = true; summary.parentElement.dispatchEvent(new Event('toggle')) })
    expect([...c.querySelectorAll('button')].find((b) => b.textContent === 'Manual worker control').disabled).toBe(false)
  })
  it('does not offer direct adjustments over an applied schedule', async () => {
    const c = await mount(true, true)
    expect(c.textContent).not.toContain('Adjust current worker capacity')
  })
  it('does not offer manual adjustments to view-only users', async () => {
    const c = await mount(false)
    expect(c.textContent).not.toContain('Adjust current worker capacity')
  })
})
