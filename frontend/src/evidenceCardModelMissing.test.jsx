import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

// What the reviewer sees when the text model is not pulled.
//
// The failure this exists for: a proposer gated on "did Ollama answer" produced no draft against a
// reachable-but-modelless Ollama, and the card showed an empty editor — indistinguishable from a
// finding that genuinely needed no fix. The server now says which model is missing and what to
// pull; these pin that it arrives ON THE CARD, both for the card that discovers it and for the
// cards the breaker spares a request.

const suggestFix = vi.fn()
vi.mock('./api.js', () => ({
  suggestFix: (...a) => suggestFix(...a),
  getFileRemediationDiffs: () => Promise.resolve([]),
  aiProvenance: () => null,
  getFileThumbnail: () => Promise.resolve(null),
  getFilePage: () => Promise.resolve(null),
  getFileGeometry: () => Promise.resolve(null),
  getScanAiCalls: () => Promise.resolve([]),
  validateAlt: () => Promise.resolve({}),
}))

const { default: EvidenceCard } = await import('./EvidenceCard.jsx')
const { resetAutoDraftBreaker } = await import('./autoDraft.js')

const DETAIL = "AI suggestion unavailable — model not pulled: Ollama is running but the text " +
               "model 'llama3.2' is not present. Run: ollama pull llama3.2"
const notPulled = () => Object.assign(new Error(DETAIL), { aiModelNotPulled: true })

// A single value-fix finding with no proposal: the auto-draft path, and the case the incident hit.
const base = { id: 1, scan_id: 's1', file: 'handbook.docx', rule_id: '2.4.4',
               rule_name: 'Link Purpose', status: 'pending', finding_count: 1 }

let mounted = []
const mount = async (item) => {
  const container = document.createElement('div'); document.body.appendChild(container)
  const root = createRoot(container)
  mounted.push({ root, container })
  await act(async () => { root.render(createElement(EvidenceCard, { item, onAct: () => {} })) })
  return container
}
const settle = async (n = 6) => {
  for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const msg = (c) => [...c.querySelectorAll('.evcard-draft-msg')].map((n) => n.textContent).join(' ')

beforeEach(() => {
  suggestFix.mockReset()
  resetAutoDraftBreaker()
})

// Unmount inside act(), rather than leaving trees standing for the environment teardown to race.
//
// Same exposure #103 fixed in inventoryAgreesWithDrawer/drawerFindingsClaim: EvidenceCard resolves
// getFileRemediationDiffs into setDiffs and the auto-draft chain into setDraftMsg, so a root left
// mounted keeps work in React's concurrent scheduler past the last assertion. If jsdom is torn down
// first, that work throws an UNHANDLED `window is not defined` — every test still reports passed and
// vitest exits non-zero on the error count alone, one full-suite run in many. Unmounting in
// beforeEach is not enough: it never runs after the LAST test, which is the one that races.
afterEach(async () => {
  for (const { root, container } of mounted) {
    await act(async () => { root.unmount() })
    container.remove()
  }
  mounted = []
})

describe('EvidenceCard — the text model is not pulled', () => {
  it('says which model is missing and what to pull, instead of an unexplained empty editor', async () => {
    suggestFix.mockRejectedValue(notPulled())
    const c = await mount({ ...base }); await settle()
    const text = msg(c)
    expect(text).toMatch(/llama3\.2/)
    expect(text).toMatch(/ollama pull llama3\.2/)
    // The old message asked the wrong question — Ollama IS running here.
    expect(text).not.toMatch(/is Ollama running/i)
  })

  it('offers the reviewer a retry, so a pull can be proven without a reload', async () => {
    suggestFix.mockRejectedValue(notPulled())
    const c = await mount({ ...base }); await settle()
    const retry = [...c.querySelectorAll('button')].find((b) => /try again/i.test(b.textContent))
    expect(retry).toBeTruthy()

    // The model is pulled now; the reviewer clicks. The breaker must not stand in the way.
    suggestFix.mockReset()
    suggestFix.mockResolvedValue({ suggestion: 'Read the 2026 benefits handbook', is_template: false, model: 'llama3.2' })
    await act(async () => { retry.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await settle()
    expect(suggestFix).toHaveBeenCalled()
    const input = c.querySelector('.evcard-rec-input')
    expect(input.value).toBe('Read the 2026 benefits handbook')
  })

  it('a second card shows the same reason WITHOUT making its own request', async () => {
    suggestFix.mockRejectedValue(notPulled())
    const first = await mount({ ...base }); await settle()
    expect(suggestFix).toHaveBeenCalledTimes(1)
    expect(msg(first)).toMatch(/ollama pull/)

    const second = await mount({ ...base, id: 2, rule_id: '2.4.9' }); await settle()
    // Spared the request — and still explained. An unexplained empty card is the defect.
    expect(suggestFix).toHaveBeenCalledTimes(1)
    expect(msg(second)).toMatch(/llama3\.2/)
    expect(msg(second)).toMatch(/ollama pull llama3\.2/)
  })

  it('an ordinary draft failure still lets the next card try', async () => {
    suggestFix.mockRejectedValueOnce(new Error('read ETIMEDOUT'))
    const first = await mount({ ...base }); await settle()
    expect(msg(first)).toMatch(/ETIMEDOUT/)

    suggestFix.mockResolvedValue({ suggestion: 'Benefits handbook (PDF)', is_template: false, model: 'llama3.2' })
    const second = await mount({ ...base, id: 2, rule_id: '2.4.9' }); await settle()
    expect(suggestFix).toHaveBeenCalledTimes(2)          // NOT suppressed by the breaker
    expect(second.querySelector('.evcard-rec-input').value).toBe('Benefits handbook (PDF)')
  })
})
