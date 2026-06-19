// Client-side PDF export (no backend). Lazy-imports jspdf + html2canvas so they
// stay out of the main bundle and only load when the user clicks Export.
export async function exportReportPDF(el, filename = 'mova-compliance-report.pdf') {
  const [{ jsPDF }, html2canvas] = await Promise.all([
    import('jspdf'),
    import('html2canvas').then((m) => m.default),
  ])
  const canvas = await html2canvas(el, { scale: 1.6, backgroundColor: '#ffffff', useCORS: true, logging: false })
  // JPEG + compression keeps it small — a PNG screenshot of this size is ~25MB, JPEG ~1–2MB
  const img = canvas.toDataURL('image/jpeg', 0.9)
  const pdf = new jsPDF('p', 'pt', 'a4', true)
  const pw = pdf.internal.pageSize.getWidth()
  const ph = pdf.internal.pageSize.getHeight()
  const margin = 24
  const imgW = pw - margin * 2
  const imgH = (canvas.height * imgW) / canvas.width

  // paginate a tall capture: shift the same image up one page-height each page
  let heightLeft = imgH
  let position = margin
  pdf.addImage(img, 'JPEG', margin, position, imgW, imgH, undefined, 'FAST')
  heightLeft -= ph - margin
  while (heightLeft > 0) {
    position = margin - (imgH - heightLeft)
    pdf.addPage()
    pdf.addImage(img, 'JPEG', margin, position, imgW, imgH, undefined, 'FAST')
    heightLeft -= ph
  }
  pdf.save(filename)
}
