// Pure, local media helpers. No network, no third party — safe to import unconditionally.
//
// These lived in aiRemediate.js, which is now behind a SIM gate so the Azure compliance build
// carries no third-party call site at all (see aiRemote.js). Statically importing them from
// there would have dragged the whole Anthropic/OpenAI module back into the bundle.

// Read a Blob/File as base64 (no data-URL prefix).
export function blobToBase64(blob) {
  return new Promise((resolve) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result).replace(/^data:[^;]+;base64,/, ''))
    r.onerror = () => resolve(null)
    r.readAsDataURL(blob)
  })
}

// All embedded raster images in an Office (OOXML) blob → [{ data(base64), mediaType, name }].
export async function allOfficeImages(blob) {
  try {
    const JSZip = (await import('jszip')).default
    const zip = await JSZip.loadAsync(blob)
    const names = Object.keys(zip.files).filter((n) => /\/media\/[^/]+\.(png|jpe?g|gif|webp)$/i.test(n))
    return Promise.all(names.map(async (n) => {
      const ext = n.split('.').pop().toLowerCase()
      const mediaType = /jpe?g/.test(ext) ? 'image/jpeg' : ext === 'gif' ? 'image/gif' : ext === 'webp' ? 'image/webp' : 'image/png'
      return { data: await zip.file(n).async('base64'), mediaType, name: n.split('/').pop() }
    }))
  } catch { return [] }
}
