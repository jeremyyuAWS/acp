import { expect, it, vi } from 'vitest'
import { readWithRetry } from './readWithRetry.js'
it('recovers a transient read with bounded exponential delays', async () => {
  const read = vi.fn().mockRejectedValueOnce(Object.assign(new Error('busy'), { status: 503 })).mockRejectedValueOnce(new TypeError('network')).mockResolvedValue('ready')
  const wait = vi.fn().mockResolvedValue()
  expect(await readWithRetry(read, { wait })).toBe('ready')
  expect(read).toHaveBeenCalledTimes(3)
  expect(wait.mock.calls[0][0]).toBeGreaterThanOrEqual(500)
  expect(wait.mock.calls[1][0]).toBeGreaterThanOrEqual(1000)
})
it('stops after three attempts and never retries permanent or authorization failures', async () => {
  for (const status of [403, 409, 422, 503]) {
    const error = Object.assign(new Error('blocked'), { status })
    const read = vi.fn().mockRejectedValue(error)
    await expect(readWithRetry(read, { wait: async () => {} })).rejects.toBe(error)
    expect(read).toHaveBeenCalledTimes(status === 503 ? 3 : 1)
  }
})
it('cancels retries when the user leaves or changes scope', async () => {
  const controller = new AbortController()
  const read = vi.fn().mockRejectedValue(new TypeError('network'))
  await expect(readWithRetry(read, { signal: controller.signal, wait: async () => controller.abort() })).rejects.toBeDefined()
  expect(read).toHaveBeenCalledTimes(1)
})
