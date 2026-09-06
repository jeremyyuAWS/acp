import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

/**
 * Which URL each ACR export actually requests.
 *
 * WRITTEN BECAUSE A BITE CHECK DID NOT BITE. Repointing `downloadAcrDocx` at `format=pdf` — so the
 * "Download accessible Word document" button would have fetched a PDF and saved it under a .docx
 * name — left the entire component suite green, twelve tests included. It could not have failed:
 * those tests mock `./acrApi` wholesale, which is right for them (they are about the screen) and
 * means the boundary between the button and the endpoint is exactly what they cannot see.
 *
 * That is the same shape as the defect this whole change exists to fix. `acr_export_docx` was
 * reachable by nobody; then reachable only through an undocumented query parameter; a button that
 * silently fetched the wrong format would have been reachable and WRONG, which is worse, because
 * the download succeeds and the file opens.
 *
 * So this file stubs `fetch` and asserts the request line and nothing else. It is deliberately not
 * a test of the screen, and deliberately not a test of the server — both of those exist.
 */

const calls = []

beforeEach(() => {
  calls.length = 0
  vi.stubGlobal('fetch', vi.fn(async (url, init) => {
    calls.push({ url: String(url), init })
    return {
      ok: true,
      status: 200,
      headers: { get: (h) => (h.toLowerCase() === 'content-disposition'
        ? 'attachment; filename="server-chose-this.docx"' : null) },
      blob: async () => new Blob(['x']),
      json: async () => ({ ok: true, failures: [], reviews: [] }),
    }
  }))
})
afterEach(() => { vi.unstubAllGlobals() })

const api = await import('./acrApi.js')

describe('the ACR export endpoints', () => {
  it('the Word download asks for format=docx, not the PDF', async () => {
    await api.downloadAcrDocx('acr_1')
    expect(calls).toHaveLength(1)
    expect(calls[0].url).toContain('/acr/acr_1/preview')
    expect(calls[0].url).toContain('format=docx')
    // The assertion the failed bite check needed. `toContain('format=docx')` alone passes on
    // `format=docx-gate` too, and `format=pdf` is the mistake that started this file.
    expect(calls[0].url).not.toContain('format=pdf')
    expect(calls[0].url.endsWith('format=docx')).toBe(true)
  })

  it('the gate asks for format=docx-gate, and is a plain JSON read', async () => {
    const body = await api.getAcrDocxGate('acr_1')
    expect(calls[0].url.endsWith('format=docx-gate')).toBe(true)
    expect(body).toEqual({ ok: true, failures: [], reviews: [] })
  })

  it('the PDF download still asks for format=pdf', async () => {
    // The control. Without it, "docx is not pdf" is satisfiable by breaking the PDF instead.
    await api.downloadAcrPdf('acr_1')
    expect(calls[0].url.endsWith('format=pdf')).toBe(true)
  })

  it('the published-revision export is a different endpoint, not a format', async () => {
    // These answer different questions — /preview renders what the report says TODAY, this
    // renders what revision N said when it was frozen — and collapsing them is how a customer
    // receives a document that does not match the revision it names.
    await api.downloadAcrRevisionPdf('acr_1', 3)
    expect(calls[0].url).toContain('/acr/acr_1/revisions/3/export')
    expect(calls[0].url).not.toContain('preview')
  })

  it('the download keeps the filename the server chose', async () => {
    // The client does not know the report's revision; the server does. Two reports downloading
    // under one name is the collision acr_export_docx.filename_for exists to prevent.
    const { filename } = await api.downloadAcrDocx('acr_1')
    expect(filename).toBe('server-chose-this.docx')
  })

  it("surfaces the server's sentence rather than a status line when it refuses", async () => {
    // A 500 here names which of ACP's own checks the generated document failed; a 503 names the
    // missing renderer. Either is the only thing an operator can act on.
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, statusText: 'Internal Server Error',
      headers: { get: () => null },
      json: async () => ({ detail: "refusing to serve the Word export: it fails ACP's own "
                                   + 'document accessibility checks (1.3.1)' }),
    })))
    await expect(api.downloadAcrDocx('acr_1')).rejects.toThrow(/1\.3\.1/)
  })
})
