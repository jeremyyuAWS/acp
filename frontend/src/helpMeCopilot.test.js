import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const readApi = (f) => readFileSync(join(here, '../../api', f), 'utf8')

describe('P2 — "Help me" copilot (ADR 0019 Phase 2 / backlog item)', () => {
  it('GET /ai/copilot route exists in routes/ai.py', () => {
    const src = readApi('routes/ai.py')
    expect(src).toMatch(/@router\.get\("\/ai\/copilot"\)/)
  })

  it('route is 403 when AI disabled', () => {
    const src = readApi('routes/ai.py')
    // The route checks get_ai_enabled() and raises 403 (on separate lines per Python convention)
    expect(src).toMatch(/get_ai_enabled/)
    expect(src).toMatch(/HTTPException\(403/)
  })

  it('route gates on cloud_vision_provider() being configured', () => {
    const src = readApi('routes/ai.py')
    expect(src).toMatch(/cloud_vision_provider\(\) is None/)
  })

  it('copilot_guidance function exists in ai.py', () => {
    const src = readApi('ai.py')
    expect(src).toMatch(/def copilot_guidance\(image_bytes/)
  })

  it('cloud gate in copilot_guidance returns None when no provider', () => {
    const src = readApi('ai.py')
    expect(src).toMatch(/cloud_vision_provider\(\)\n\s+if cloud is None:\n\s+return None/)
  })

  it('copilot call is traced with surface="copilot"', () => {
    const src = readApi('ai.py')
    expect(src).toMatch(/_trace_ai\("copilot"/)
  })

  it('getCopilotGuidance is exported from api.js', () => {
    const src = read('api.js')
    expect(src).toMatch(/export const getCopilotGuidance/)
  })

  it('getCopilotGuidance hits /ai/copilot endpoint', () => {
    const src = read('api.js')
    expect(src).toMatch(/\/ai\/copilot/)
  })

  it('getCopilotGuidance has a SIM-mode stub', () => {
    const src = read('api.js')
    expect(src).toMatch(/getCopilotGuidance.*SIM\s*\n.*sim\(|getCopilotGuidance = .*SIM.*\n.*sim\(/s)
  })

  it('EvidenceCard imports getCopilotGuidance', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/getCopilotGuidance/)
  })

  it('copilot button is gated on cloudEnabled in EvidenceCard', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/cloudEnabled.*Help me understand this image|Help me understand this image.*cloudEnabled/s)
  })

  it('copilot guidance callout is distinct from a draft textarea', () => {
    const src = read('EvidenceCard.jsx')
    // Guidance appears in a <div role="note">, never in a <textarea>
    expect(src).toMatch(/AI guidance — not a draft/)
    // The guidance label and a textarea opener must not appear on the same line
    expect(src).not.toMatch(/AI guidance — not a draft.*<textarea|<textarea.*AI guidance — not a draft/)
  })

  it('copilot button only shows for usingEvidence + sc 1.1.1 cards', () => {
    const src = read('EvidenceCard.jsx')
    expect(src).toMatch(/usingEvidence && cloudEnabled && card\.sc === '1\.1\.1'/)
  })
})
