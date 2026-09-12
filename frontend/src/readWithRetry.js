// For read-only requests. Never replay a write whose outcome may be unknown.
export async function readWithRetry(read, { signal, wait = abortableWait } = {}) {
  for (let attempt = 0; ; attempt++) {
    signal?.throwIfAborted()
    try { return await read() }
    catch (error) {
      const transient = error instanceof TypeError || [408, 429, 502, 503, 504].includes(error.status)
      if (signal?.aborted || !transient || attempt >= 2) throw error
      await wait(500 * 2 ** attempt + Math.floor(Math.random() * 250), signal)
    }
  }
}
function abortableWait(ms, signal) {
  return new Promise((resolve, reject) => {
    signal?.throwIfAborted()
    const abort = () => { clearTimeout(timer); reject(signal.reason) }
    const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve() }, ms)
    signal?.addEventListener('abort', abort, { once: true })
  })
}
