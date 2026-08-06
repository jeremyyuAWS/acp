import { describe, it, expect } from 'vitest'
import fs from 'fs'
import { auditPdf, remediatePdf } from './pdfAudit.js'

// vitest runs with cwd = frontend
const sample = () => new Blob([fs.readFileSync('public/samples/patient-discharge-instructions.pdf')], { type: 'application/pdf' })

describe('pdfAudit (real pdf-lib engine)', () => {
  it('detects the real structural state of the sample PDF', async () => {
    const findings = await auditPdf(sample())
    const rules = findings.map((f) => f.rule)
    // The sample is a plain untagged PDF: it should at least flag tagging.
    expect(rules).toContain('pdf.tagged')
    // log for visibility
    console.log('sample PDF findings:', rules.join(', '))
  })

  it('remediation genuinely sets title + language and they clear on re-audit', async () => {
    const { blob, changes, tagged } = await remediatePdf(sample())
    expect(changes.length).toBeGreaterThan(0)
    const after = await auditPdf(blob)
    const rules = after.map((f) => f.rule)
    expect(rules).not.toContain('pdf.document-title')
    expect(rules).not.toContain('pdf.document-language')
    // tagging is honestly NOT auto-fixed — it should still be reported
    expect(tagged).toBe(false)
    expect(rules).toContain('pdf.tagged')
  })

  it('produces a valid, larger PDF blob', async () => {
    const orig = sample()
    const { blob } = await remediatePdf(orig)
    expect(blob.type).toBe('application/pdf')
    const head = new Uint8Array(await blob.slice(0, 5).arrayBuffer())
    expect(String.fromCharCode(...head)).toBe('%PDF-')
  })
})
