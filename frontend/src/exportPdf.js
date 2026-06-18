// Client-side PDF export (no backend). Lazy-imports jspdf + html2canvas so they
// stay out of the main bundle and only load when the user clicks Export.
export async function exportReportPDF(el, filename = 'mova-compliance-report.pdf') {
  const [{ jsPDF }, html2canvas] = await Promise.all([
    import('jspdf'),
    import('html2canvas').then((m) => m.default),
  ])
  const canvas = await html2canvas(el, { scale: 2, backgroundColor: '#faf8fb', useCORS: true, logging: false })
  const img = canvas.toDataURL('image/png')
  const pdf = new jsPDF('p', 'pt', 'a4')
  const pw = pdf.internal.pageSize.getWidth()
  const ph = pdf.internal.pageSize.getHeight()
  const margin = 24
  const imgW = pw - margin * 2
  const imgH = (canvas.height * imgW) / canvas.width

  // paginate a tall capture: shift the same image up one page-height each page
  let heightLeft = imgH
  let position = margin
  pdf.addImage(img, 'PNG', margin, position, imgW, imgH)
  heightLeft -= ph - margin
  while (heightLeft > 0) {
    position = margin - (imgH - heightLeft)
    pdf.addPage()
    pdf.addImage(img, 'PNG', margin, position, imgW, imgH)
    heightLeft -= ph
  }
  pdf.save(filename)
}
