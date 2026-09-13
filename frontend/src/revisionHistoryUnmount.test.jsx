import { expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ effects: [], update: vi.fn(), request: vi.fn() }))
vi.mock('react', async (original) => ({ ...(await original()),
  useState: () => [{ loading: true, revisions: [] }, mocks.update],
  useRef: value => ({ current: value }),
  useEffect: effect => { mocks.effects.push(effect) },
}))
vi.mock('./api.js', () => ({ getWorkerRevisions: mocks.request }))
import RevisionHistoryPanel from './RevisionHistoryPanel.jsx'
it.each(['resolve', 'reject'])('ignores a late revision request %s after unmount', async outcome => {
  mocks.effects.length = 0
  mocks.update.mockClear()
  let resolve, reject
  mocks.request.mockReturnValue(new Promise((yes, no) => { resolve = yes; reject = no }))
  RevisionHistoryPanel()
  const cleanup = mocks.effects[0]()
  cleanup?.()
  mocks.update.mockClear()
  if (outcome === 'resolve') resolve({ configured: true, revisions: [] })
  else reject(new Error('network'))
  await Promise.resolve()
  await Promise.resolve()
  expect(mocks.update).not.toHaveBeenCalled()
})
