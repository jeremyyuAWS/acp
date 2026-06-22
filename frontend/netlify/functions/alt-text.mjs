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
        max_tokens: 160,
        system: 'You write alternative text for images embedded in business documents, for screen-reader users (WCAG 1.1.1). Be specific and concise: one sentence, no more than ~140 characters, no "image of"/"picture of" preamble, present the essential information or function the image conveys. If it is a chart, state what it shows and the key figures. Output ONLY the alt text.',
        messages: [{ role: 'user', content: [
          { type: 'image', source: { type: 'base64', media_type: mediaType, data: image } },
          { type: 'text', text: hint ? `Context: ${String(hint).slice(0, 200)}. Write the alt text.` : 'Write the alt text for this image.' },
        ] }],
      }),
    })
    const data = await res.json()
    let alt = data?.content?.[0]?.text?.trim() || null
    if (alt) alt = alt.replace(/^["“]|["”]$/g, '').replace(/\s+/g, ' ').slice(0, 200)
    return { statusCode: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ alt, model: data?.model || null }) }
  } catch {
    return { statusCode: 200, body: JSON.stringify({ alt: null }) }
  }
}
