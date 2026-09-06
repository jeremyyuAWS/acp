/**
 * Recover a tab that was open across a deploy.
 *
 * Every view behind `lazy(() => import(...))` — Live Operations, the knowledge graph, the live
 * notifier (App.jsx) — is its own content-hashed chunk, fetched the first time the view opens.
 * A deploy replaces those filenames. A tab still holding the OLD index.html then asks for a
 * chunk that no longer exists, the import rejects, and the reader gets ErrorBoundary's generic
 * "Something went wrong" for a page that is not broken and a deploy that succeeded. On
 * 2026-09-06 nine PRs merged inside an hour and that is exactly what an open tab showed.
 *
 * Vite's build wraps every dynamic import in `__vitePreload`, which fires a cancelable
 * `vite:preloadError` on window when the fetch fails. Calling preventDefault stops it being
 * rethrown, so we can reload into the new build instead of rendering an error.
 *
 * THE LOOP IS THE THING TO GET RIGHT. A handler that reloads on every failure turns a genuinely
 * broken deploy — or an offline tab — into an infinite refresh, which is far worse than the
 * error boundary it replaces. So a reload is allowed only if this tab has not already reloaded
 * for this reason in the last RELOAD_COOLDOWN_MS. One stale-chunk load reloads once; if the very
 * next load fails too, the cause is not a stale chunk and the reader sees the error boundary,
 * which is the honest outcome. The window is short rather than once-per-session so a SECOND
 * deploy, later in the same long-lived tab, still recovers.
 *
 * sessionStorage, not localStorage: the guard is per tab, because the reload is per tab. Every
 * access is wrapped — it throws rather than returning null in a private window or with site data
 * blocked — and a guard that cannot be read must NOT be treated as "no recent reload", or the
 * loop protection is exactly what fails first.
 */
export const RELOAD_KEY = 'acp.chunkReloadAt'
export const RELOAD_COOLDOWN_MS = 10000

/**
 * @param listen   window.addEventListener, or a seam for tests
 * @param reload   window.location.reload, or a seam
 * @param storage  sessionStorage, or a seam
 * @param now      Date.now, or a seam
 */
export function installChunkReloadHandler({
  listen, reload, storage, now = () => Date.now(),
} = {}) {
  const target = listen || (typeof window !== 'undefined'
    ? window.addEventListener.bind(window) : null)
  if (!target) return null

  const read = () => {
    try {
      const held = storage ?? window.sessionStorage
      const raw = Number(held.getItem(RELOAD_KEY))
      return Number.isFinite(raw) && raw > 0 ? raw : null
    } catch {
      // Unreadable is NOT "never reloaded". Treated as a reload that just happened, so a browser
      // that cannot remember the guard degrades to showing the error boundary rather than to an
      // unbounded refresh loop.
      return Infinity
    }
  }
  const write = (at) => {
    try { (storage ?? window.sessionStorage).setItem(RELOAD_KEY, String(at)) } catch { /* no guard to keep */ }
  }

  const handler = (event) => {
    // Stops Vite rethrowing the failure, so nothing reaches the error boundary while we reload.
    event?.preventDefault?.()
    const last = read()
    const at = now()
    if (last !== null && at - last < RELOAD_COOLDOWN_MS) return false
    write(at)
    ;(reload || (() => window.location.reload()))()
    return true
  }
  target('vite:preloadError', handler)
  return handler
}
