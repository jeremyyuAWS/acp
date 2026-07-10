// Client bridge to the real AI remediation endpoints. The browser never sees the
// NOTE: every function below POSTs to /.netlify/functions/*, which exist only in the Netlify
// prototype. The ACP deployment has no such endpoints — these calls 404 and fall back. They
// do NOT run in production, and ACP's real AI path is the local Ollama model (api/ai.py).
// degrades gracefully to null so the demo still works with no key (local dev), exactly
// like the chat path.

// Alt text for an image (WCAG 1.1.1) — Netlify-prototype path only; see the note above.
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
    return { alt: j?.alt || null, text: j?.text || null }
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

// Captions/transcript (1.2.2/1.2.3) — Netlify-prototype path only. ACP itself never transcribes.
// Returns WebVTT text, or null offline. `audio` is base64 (or a data URL).
export async function generateCaptions({ audio, mediaType, audioUrl } = {}) {
  if (!audio && !audioUrl) return null
  try {
    const res = await fetch('/.netlify/functions/transcribe', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ audio, mediaType, audioUrl }),
    })
    if (!res.ok) return null
    const j = await res.json()
    return j?.vtt || null
  } catch { return null }
}

// LLM-powered executive narrative for the per-document report. Returns
// { headline, summary, impact, recommendation } or null offline.
export async function generateInsights({ file, score, finalScore, engine, findings } = {}) {
  try {
    const res = await fetch('/.netlify/functions/insights', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ file, score, finalScore, engine, findings }),
    })
    if (!res.ok) return null
    const j = await res.json()
    return j?.insight || null
  } catch { return null }
}

// Read a Blob/File as base64 (no data-URL prefix) for posting to a function.
export function blobToBase64(blob) {
  return new Promise((resolve) => {
    const r = new FileReader()
    r.onload = () => resolve(String(r.result).replace(/^data:[^;]+;base64,/, ''))
    r.onerror = () => resolve(null)
    r.readAsDataURL(blob)
  })
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

// All embedded raster images in an Office (OOXML) blob → [{ data(base64), mediaType, name(basename) }].
// Used to generate per-image alt text rather than one description for the whole document.
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
