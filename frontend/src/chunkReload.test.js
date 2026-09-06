/**
 * Recovering a tab that was open across a deploy — and, more importantly, NOT turning a broken
 * deploy into an infinite refresh.
 *
 * Written after 2026-09-06, when nine PRs merged inside an hour and an open tab showed
 * ErrorBoundary's "Something went wrong" on Live Operations: the view is lazy-loaded, its
 * content-hashed chunk had been replaced, and the old index.html was asking for a filename that
 * no longer existed.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { installChunkReloadHandler, RELOAD_KEY, RELOAD_COOLDOWN_MS } from './chunkReload.js'

function harness({ storage, startAt = 1_000_000 } = {}) {
  const listened = []
  const reload = vi.fn()
  let clock = startAt
  const store = storage ?? (() => {
    const map = new Map()
    return {
      getItem: (k) => (map.has(k) ? map.get(k) : null),
      setItem: (k, v) => map.set(k, v),
    }
  })()
  const handler = installChunkReloadHandler({
    listen: (name, fn) => listened.push([name, fn]),
    reload, storage: store, now: () => clock,
  })
  return { handler, reload, listened, store, tick: (ms) => { clock += ms } }
}

const failure = () => ({ preventDefault: vi.fn() })

describe('chunk reload handler', () => {
  it('listens for the event Vite actually fires', () => {
    // `vite:preloadError` is emitted by the __vitePreload helper the build wraps every dynamic
    // import in. A different name here is a handler that never runs, and nothing would say so.
    const { listened } = harness()
    expect(listened.map(([name]) => name)).toEqual(['vite:preloadError'])
  })

  it('reloads once into the new build', () => {
    const { handler, reload } = harness()
    const event = failure()
    expect(handler(event)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(1)
    // preventDefault stops Vite rethrowing, so the error boundary does not flash up while the
    // reload is in flight.
    expect(event.preventDefault).toHaveBeenCalled()
  })

  it('does not reload a second time inside the cooldown', () => {
    // THE FAILURE THIS GUARD EXISTS FOR. If the reload did not fix it, the cause is not a stale
    // chunk, and refreshing forever is far worse than the error boundary it replaces.
    const { handler, reload, tick } = harness()
    handler(failure())
    tick(RELOAD_COOLDOWN_MS - 1)
    expect(handler(failure())).toBe(false)
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('recovers from a later deploy in the same long-lived tab', () => {
    // Which is why the guard is a short cooldown rather than once-per-session: a tab left open
    // all day sees more than one deploy.
    const { handler, reload, tick } = harness()
    handler(failure())
    tick(RELOAD_COOLDOWN_MS + 1)
    expect(handler(failure())).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
  })

  it('records when it reloaded, so a fresh page load can see it', () => {
    // The guard has to survive the reload itself — it is read by the NEXT page load, not by this
    // one. A guard held in memory would be gone exactly when it is needed.
    const { handler, store } = harness({ startAt: 1_234_000 })
    handler(failure())
    expect(Number(store.getItem(RELOAD_KEY))).toBe(1_234_000)
  })

  it('treats an unreadable guard as "just reloaded", never as "never reloaded"', () => {
    // sessionStorage THROWS rather than returning null in a private window or with site data
    // blocked. Reading that as "no recent reload" would make the loop protection the first thing
    // to fail, in exactly the browsers least able to recover from a loop.
    const blocked = {
      getItem: () => { throw new Error('site data blocked') },
      setItem: () => { throw new Error('site data blocked') },
    }
    const { handler, reload } = harness({ storage: blocked })
    expect(handler(failure())).toBe(false)
    expect(reload).not.toHaveBeenCalled()
  })

  it('is installed before the app renders', async () => {
    // A chunk can fail on the very first lazy view opened, so the listener must already exist.
    const { readFileSync } = await import('node:fs')
    const { fileURLToPath } = await import('node:url')
    const { dirname, join } = await import('node:path')
    const here = dirname(fileURLToPath(import.meta.url))
    const main = readFileSync(join(here, 'main.jsx'), 'utf8')
    expect(main.indexOf('installChunkReloadHandler()'))
      .toBeLessThan(main.indexOf('createRoot('))
  })
})

describe('chunk reload handler, wired the way main.jsx wires it', () => {
  // Every test above passes seams. main.jsx calls installChunkReloadHandler() with NO arguments,
  // so the real window/sessionStorage path is the one that actually ships and was the one path
  // nothing exercised.
  beforeEach(() => { try { window.sessionStorage.clear() } catch { /* blocked */ } })

  it('attaches to window and remembers through sessionStorage', () => {
    const reloads = []
    const original = window.location
    // jsdom's location.reload is not implemented and logs "Not implemented: navigation"; the
    // handler is given a seam for the navigation only, so the LISTENER and the STORAGE are still
    // the real ones this assertion is about.
    const handler = installChunkReloadHandler({ reload: () => reloads.push(1) })
    expect(handler).toBeTruthy()

    const event = new Event('vite:preloadError', { cancelable: true })
    window.dispatchEvent(event)

    expect(reloads).toHaveLength(1)
    expect(event.defaultPrevented).toBe(true)
    expect(Number(window.sessionStorage.getItem(RELOAD_KEY))).toBeGreaterThan(0)
    expect(window.location).toBe(original)

    // And the guard holds across a second event, which is the loop protection working through
    // real sessionStorage rather than through a fake.
    window.dispatchEvent(new Event('vite:preloadError', { cancelable: true }))
    expect(reloads).toHaveLength(1)
  })
})
