// Client bridge to the real AI remediation endpoints. The browser never sees the
// Anthropic key — it POSTs to the serverless function, which calls Claude. Every call
// degrades gracefully to null so the demo still works with no key (local dev), exactly
// like the chat path.

// Generate genuine alt text for an image via Claude vision (WCAG 1.1.1).
export async function generateAltText({ data, mediaType, hint } = {}) {
  if (!data) return null
  try {
    const res = await fetch('/.netlify/functions/alt-text', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ image: data, mediaType, hint }),
    })
    if (!res.ok) return null
    const j = await res.json()
    return j?.alt || null
  } catch { return null }
}

// Real AI fix for the text-based criteria (link purpose 2.4.4, sensory 1.3.3,
// language of parts 3.1.2). Returns the drafted fix string, or null offline.
export async function aiTextFix({ kind, text, context } = {}) {
  if (!text) return null
  try {
    const res = await fetch('/.netlify/functions/ai-fix', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ kind, text, context }),
    })
    if (!res.ok) return null
    const j = await res.json()
    return j?.fix || null
  } catch { return null }
}

// Pull the first embedded raster image out of an Office (OOXML) blob → { data(base64), mediaType }.
export async function firstOfficeImage(blob) {
  try {
    const JSZip = (await import('jszip')).default
    const zip = await JSZip.loadAsync(blob)
    const name = Object.keys(zip.files).find((n) => /\/media\/[^/]+\.(png|jpe?g|gif|webp)$/i.test(n))
    if (!name) return null
    const ext = name.split('.').pop().toLowerCase()
    const mediaType = /jpe?g/.test(ext) ? 'image/jpeg' : ext === 'gif' ? 'image/gif' : ext === 'webp' ? 'image/webp' : 'image/png'
    return { data: await zip.file(name).async('base64'), mediaType, name }
  } catch { return null }
}
