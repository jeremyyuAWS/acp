// Real AI alt-text generation (WCAG 1.1.1). The browser POSTs an image
// ({ image: base64 [or data URL], mediaType }) and this calls Claude's vision model
// with the key kept server-side, returning { alt } — the genuine description the
// platform writes back into the remediated document.
//
// Enable by setting ANTHROPIC_API_KEY in Netlify env (optionally ANTHROPIC_VISION_MODEL).
// With no key it returns { alt: null } so the client falls back to a placeholder and
// the demo still works.
const ALLOWED = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

export async function handler(event) {
  if (event.httpMethod !== 'POST') return { statusCode: 405, body: 'Method not allowed' }
  const key = process.env.ANTHROPIC_API_KEY
  if (!key) return { statusCode: 200, body: JSON.stringify({ alt: null }) }

  let body = {}
  try { body = JSON.parse(event.body || '{}') } catch { /* ignore */ }
  let { image, mediaType, hint } = body
  if (!image) return { statusCode: 400, body: JSON.stringify({ alt: null }) }
  // accept a full data URL or raw base64
  const m = /^data:([^;]+);base64,(.*)$/s.exec(image)
  if (m) { mediaType = mediaType || m[1]; image = m[2] }
  mediaType = (mediaType || 'image/png').toLowerCase()
  if (!ALLOWED.has(mediaType)) return { statusCode: 200, body: JSON.stringify({ alt: null }) }

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: process.env.ANTHROPIC_VISION_MODEL || 'claude-opus-4-8',
        max_tokens: 400,
        system: 'You analyze an image embedded in a business document for accessibility. Return ONLY a compact JSON object with two string fields and nothing else: "alt" — concise alt text for screen-reader users (WCAG 1.1.1; ~140 chars, no "image of"/"picture of" preamble, the essential info/function; for a chart state what it shows and the key figures); "text" — if the image is PRIMARILY rendered text (an image of text: a banner, scanned headline, infographic of words), the verbatim text content (WCAG 1.4.5); otherwise an empty string.',
        messages: [{ role: 'user', content: [
          { type: 'image', source: { type: 'base64', media_type: mediaType, data: image } },
          { type: 'text', text: hint ? `Context: ${String(hint).slice(0, 200)}. Return the JSON.` : 'Return the JSON.' },
        ] }],
      }),
    })
    const data = await res.json()
    const raw = data?.content?.[0]?.text?.trim() || ''
    let alt = null, text = ''
    try { const j = JSON.parse(raw.replace(/^```json\s*|\s*```$/g, '')); alt = (j.alt || '').trim() || null; text = (j.text || '').trim() }
    catch { alt = raw.replace(/^["“]|["”]$/g, '').replace(/\s+/g, ' ').slice(0, 200) || null }
    if (alt) alt = alt.replace(/\s+/g, ' ').slice(0, 220)
    return { statusCode: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ alt, text: text || null, model: data?.model || null }) }
  } catch {
    return { statusCode: 200, body: JSON.stringify({ alt: null }) }
  }
}
