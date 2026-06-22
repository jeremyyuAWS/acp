// REAL PDF accessibility detection + remediation in the browser via pdf-lib (lazy-loaded).
// We genuinely parse the PDF and check/repair the mechanical structural properties — the
// document title, the language, and whether the PDF is tagged. Title + language are fixed
// for real and written back into a downloadable file; full tagging / reading-order
// re-authoring needs a heavier structural engine, so it is detected and flagged honestly,
// never faked.
const N = async () => (await import('pdf-lib'))

export async function auditPdf(blob) {
  const { PDFDocument, PDFName } = await N()
  const doc = await PDFDocument.load(await blob.arrayBuffer(), { ignoreEncryption: true, updateMetadata: false })
  const findings = []
  const title = doc.getTitle()
  if (!title || !title.trim()) findings.push({ rule: 'pdf-title', wcag: '2.4.2 page titled', sev: 'SERIOUS', detail: 'document has no title' })
  if (!doc.catalog.get(PDFName.of('Lang'))) findings.push({ rule: 'pdf-lang', wcag: '3.1.1 language of page', sev: 'MODERATE', detail: 'document language is not declared' })
  const tagged = !!doc.catalog.get(PDFName.of('StructTreeRoot'))
  if (!tagged) findings.push({ rule: 'pdf-tagged', wcag: '1.3.1 info & relationships', sev: 'CRITICAL', detail: 'PDF is not tagged — structure & reading order are not exposed to assistive tech' })
  return findings
}

// Apply the mechanical fixes (title + language + DisplayDocTitle) and return a genuinely
// modified PDF blob. `tagged` is reported back so callers can show what still needs the
// structural re-authoring engine.
export async function remediatePdf(blob, { title } = {}) {
  const { PDFDocument, PDFName, PDFString } = await N()
  const doc = await PDFDocument.load(await blob.arrayBuffer(), { ignoreEncryption: true, updateMetadata: false })
  const changes = []
  if (!doc.getTitle() || !doc.getTitle().trim()) { doc.setTitle(title || 'Remediated — mova.io', { showInWindowTitleBar: true }); changes.push('document title set · 2.4.2') }
  if (!doc.catalog.get(PDFName.of('Lang'))) { doc.catalog.set(PDFName.of('Lang'), PDFString.of('en-US')); changes.push('language set to en-US · 3.1.1') }
  const tagged = !!doc.catalog.get(PDFName.of('StructTreeRoot'))
  const out = await doc.save()
  return { blob: new Blob([out], { type: 'application/pdf' }), changes, tagged }
}
