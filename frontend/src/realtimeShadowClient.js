// Deliberately distinct from the legacy per-scan `/events` snapshot stream. This endpoint is the
// versioned multiplexed feed backed by the isolated `realtime:v1` namespace.
import { getRealtimeAuthoritativeSnapshot, getRealtimeStreamRequest } from './api.js'

const SEEN_LIMIT = 2048

export const REALTIME_SHADOW_ENABLED = import.meta.env.VITE_REALTIME_SHADOW_ENABLED === 'true'

function parseFrame(block) {
  const lines = block.split(/\r?\n/)
  const type = lines.find((line) => line.startsWith('event:'))?.slice(6).trim() || 'message'
  const id = lines.find((line) => line.startsWith('id:'))?.slice(3).trim() || null
  const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
  if (!data) return null
  try { return { type, id, data: JSON.parse(data) } } catch { return null }
}

function validEnvelope(event) {
  return event && typeof event.event_id === 'string' && /^1\.\d+$/.test(event.schema_version)
    && typeof event.kind === 'string' && typeof event.owner_scope === 'string'
    && typeof event.occurred_at === 'string' && Number.isInteger(event.priority)
    && Object.hasOwn(event, 'payload')
}

const streamTuple = (id) => /^\d+-\d+$/.test(id || '') ? id.split('-').map(Number) : null
const after = (candidate, prior) => {
  const a = streamTuple(candidate); const b = streamTuple(prior)
  return a && (!b || a[0] > b[0] || (a[0] === b[0] && a[1] > b[1]))
}

export class RealtimeShadowClient {
  constructor({ endpoint, headersProvider, snapshotProvider = getRealtimeAuthoritativeSnapshot, fetchImpl = globalThis.fetch, retryMs = 1000, coalesceMs = 100 } = {}) {
    this.endpoint = endpoint
    this.headersProvider = headersProvider
    this.snapshotProvider = snapshotProvider
    this.fetchImpl = fetchImpl
    this.retryMs = retryMs
    this.coalesceMs = coalesceMs
    this.listeners = new Set()
    this.eventListeners = new Set()
    this.seen = new Set()
    this.seenOrder = []
    this.health = { state: 'idle', latencyMs: null, lastEventId: null, reconnects: 0, error: null }
    this.controller = null
    this.retryTimer = null
    this.progressTimer = null
    this.pendingProgress = new Map()
  }

  subscribe(listener) { this.listeners.add(listener); listener(this.health); return () => this.listeners.delete(listener) }
  onEvent(listener) { this.eventListeners.add(listener); return () => this.eventListeners.delete(listener) }
  snapshot() { return this.health }
  publish(patch) { this.health = { ...this.health, ...patch }; this.listeners.forEach((fn) => fn(this.health)) }

  start() {
    if (this.controller || this.retryTimer) return
    this.connect()
  }

  stop() {
    this.controller?.abort()
    this.controller = null
    clearTimeout(this.retryTimer); this.retryTimer = null
    clearTimeout(this.progressTimer); this.progressTimer = null
    this.pendingProgress.clear()
    this.publish({ state: 'idle' })
  }

  scheduleReconnect(error) {
    if (this.retryTimer) return
    this.publish({ state: 'fallback', error: error?.message || 'Realtime connection unavailable' })
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null
      this.publish({ reconnects: this.health.reconnects + 1 })
      this.connect()
    }, this.retryMs)
  }

  async connect() {
    const controller = new AbortController()
    this.controller = controller
    this.publish({ state: 'connecting', error: null })
    try {
      const request = this.endpoint
        ? { endpoint: this.endpoint, headers: this.headersProvider?.() || {} }
        : getRealtimeStreamRequest()
      const headers = { ...request.headers, Accept: 'text/event-stream' }
      if (this.health.lastEventId) headers['Last-Event-ID'] = this.health.lastEventId
      const response = await this.fetchImpl(request.endpoint, { headers, signal: controller.signal, credentials: 'same-origin' })
      if (!response.ok || !response.body) throw new Error(`Realtime stream returned ${response.status}`)
      this.publish({ state: 'connected' })
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split(/\r?\n\r?\n/)
        buffer = blocks.pop()
        for (const block of blocks) {
          const frame = parseFrame(block)
          if (!frame) continue
          if (frame.type === 'acp-event') this.accept(frame.data, frame.id)
          else if (frame.type === 'reconciliation-required') await this.reconcile(frame.data?.reason)
          else if (frame.type === 'snapshot') this.deliverSnapshot(frame.data)
        }
      }
      if (!controller.signal.aborted) throw new Error('Realtime stream ended')
    } catch (error) {
      if (!controller.signal.aborted) this.scheduleReconnect(error)
    } finally {
      if (this.controller === controller) this.controller = null
    }
  }

  accept(event, frameId = event?.stream_id) {
    if (!validEnvelope(event) || !after(frameId, this.health.lastEventId) || this.seen.has(event.event_id)) return false
    if (event.stream_id && event.stream_id !== frameId) return false
    this.seen.add(event.event_id); this.seenOrder.push(event.event_id)
    if (this.seenOrder.length > SEEN_LIMIT) this.seen.delete(this.seenOrder.shift())
    const latencyMs = Math.max(0, Date.now() - Date.parse(event.occurred_at))
    this.publish({ state: 'connected', latencyMs, lastEventId: frameId, error: null })
    const orderKey = event.coalesce_key || event.scan_id || event.job_id || event.kind
    if (event.priority === 3 && event.kind.endsWith('.progressed')) {
      this.pendingProgress.set(orderKey, event)
      if (!this.progressTimer) this.progressTimer = setTimeout(() => this.flushProgress(), this.coalesceMs)
    } else {
      this.eventListeners.forEach((fn) => fn(event))
    }
    return true
  }

  flushProgress() {
    this.progressTimer = null
    const events = [...this.pendingProgress.values()].sort((a, b) => {
      const left = streamTuple(a.stream_id); const right = streamTuple(b.stream_id)
      return left[0] - right[0] || left[1] - right[1]
    })
    this.pendingProgress.clear()
    events.forEach((event) => this.eventListeners.forEach((fn) => fn(event)))
  }

  deliverSnapshot(snapshot) {
    this.eventListeners.forEach((fn) => fn({ kind: 'snapshot', payload: { snapshot }, control: true }))
  }

  async reconcile(reason) {
    this.publish({ state: 'reconciling', error: reason || 'Realtime history needs reconciliation' })
    try {
      this.deliverSnapshot(await this.snapshotProvider())
      this.publish({ state: 'connected', lastEventId: null, error: null })
    } catch (error) {
      this.scheduleReconnect(error)
    }
  }
}

let sharedClient
export function getRealtimeShadowClient() {
  if (!sharedClient) sharedClient = new RealtimeShadowClient()
  return sharedClient
}
