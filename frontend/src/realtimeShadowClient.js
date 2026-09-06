// Deliberately distinct from the legacy per-scan `/events` snapshot stream. This endpoint is the
// versioned multiplexed feed backed by the isolated `realtime:v1` namespace.
const DEFAULT_ENDPOINT = '/api/realtime/v1/stream'
const SEEN_LIMIT = 2048

export const REALTIME_SHADOW_ENABLED = import.meta.env.VITE_REALTIME_SHADOW_ENABLED === 'true'

function parseFrame(block) {
  const lines = block.split(/\r?\n/)
  const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
  if (!data) return null
  try { return JSON.parse(data) } catch { return null }
}

function validEnvelope(event) {
  return event && typeof event.event_id === 'string' && event.event_version === 1
    && typeof event.event_type === 'string' && typeof event.occurred_at === 'string'
    && typeof event.tenant_id === 'string' && typeof event.correlation_id === 'string'
    && typeof event.source === 'string' && typeof event.priority === 'string'
    && Number.isFinite(event.sequence) && Object.hasOwn(event, 'payload')
}

export class RealtimeShadowClient {
  constructor({ endpoint = DEFAULT_ENDPOINT, fetchImpl = globalThis.fetch, retryMs = 1000, coalesceMs = 100 } = {}) {
    this.endpoint = endpoint
    this.fetchImpl = fetchImpl
    this.retryMs = retryMs
    this.coalesceMs = coalesceMs
    this.listeners = new Set()
    this.eventListeners = new Set()
    this.seen = new Set()
    this.seenOrder = []
    this.sequences = new Map()
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
      const headers = { Accept: 'text/event-stream' }
      if (this.health.lastEventId) headers['Last-Event-ID'] = this.health.lastEventId
      const response = await this.fetchImpl(this.endpoint, { headers, signal: controller.signal, credentials: 'same-origin' })
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
        blocks.forEach((block) => { const event = parseFrame(block); if (event) this.accept(event) })
      }
      if (!controller.signal.aborted) throw new Error('Realtime stream ended')
    } catch (error) {
      if (!controller.signal.aborted) this.scheduleReconnect(error)
    } finally {
      if (this.controller === controller) this.controller = null
    }
  }

  accept(event) {
    if (!validEnvelope(event) || this.seen.has(event.event_id)) return false
    const orderKey = `${event.tenant_id}:${event.source}:${event.correlation_id}`
    const prior = this.sequences.get(orderKey) ?? -1
    if (event.sequence <= prior) return false
    this.sequences.set(orderKey, event.sequence)
    this.seen.add(event.event_id); this.seenOrder.push(event.event_id)
    if (this.seenOrder.length > SEEN_LIMIT) this.seen.delete(this.seenOrder.shift())
    const latencyMs = Math.max(0, Date.now() - Date.parse(event.occurred_at))
    this.publish({ state: 'connected', latencyMs, lastEventId: event.event_id, error: null })
    if (event.priority === 'low' && event.event_type.endsWith('.progress')) {
      this.pendingProgress.set(orderKey, event)
      if (!this.progressTimer) this.progressTimer = setTimeout(() => this.flushProgress(), this.coalesceMs)
    } else {
      this.eventListeners.forEach((fn) => fn(event))
    }
    return true
  }

  flushProgress() {
    this.progressTimer = null
    const events = [...this.pendingProgress.values()].sort((a, b) => a.sequence - b.sequence)
    this.pendingProgress.clear()
    events.forEach((event) => this.eventListeners.forEach((fn) => fn(event)))
  }
}

let sharedClient
export function getRealtimeShadowClient() {
  if (!sharedClient) sharedClient = new RealtimeShadowClient()
  return sharedClient
}
