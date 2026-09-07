// Small request coordinator for policy evidence. A workflow revision is part of the identity:
// evidence from revision 7 must never repaint revision 8 merely because its request finished last.
export function createReviewEvidenceCache(fetchEvidence) {
  const cache = new Map()
  let request = 0

  return {
    load(scanId, revision, { refresh = false } = {}) {
      const key = `${scanId || ''}:${revision ?? 'unknown'}`
      if (refresh) cache.delete(key)
      let pending = cache.get(key)
      if (!pending) {
        const id = ++request
        pending = Promise.resolve(fetchEvidence(scanId)).then((value) => ({ key, id, value }))
        cache.set(key, pending)
        pending.catch(() => { if (cache.get(key) === pending) cache.delete(key) })
      }
      return pending
    },
    key(scanId, revision) { return `${scanId || ''}:${revision ?? 'unknown'}` },
    clear() { cache.clear() },
  }
}
