// Real captions + transcript (WCAG 1.2.2 / 1.2.3) via speech-to-text. Claude has no
// audio input, so this uses OpenAI Whisper (OPENAI_API_KEY, server-side) to transcribe
// audio → WebVTT captions. The browser POSTs { audio: base64 [or data URL], mediaType }
// or { audioUrl }. Returns { vtt }. Graceful null fallback with no key.
export async function handler(event) {
  if (event.httpMethod !== 'POST') return { statusCode: 405, body: 'Method not allowed' }
  const key = process.env.OPENAI_API_KEY
  if (!key) return { statusCode: 200, body: JSON.stringify({ vtt: null }) }

  let body = {}
  try { body = JSON.parse(event.body || '{}') } catch { /* ignore */ }
  let { audio, mediaType, audioUrl } = body
  let buf = null
  if (audioUrl) {
    try { buf = Buffer.from(await (await fetch(audioUrl)).arrayBuffer()) } catch { return { statusCode: 200, body: JSON.stringify({ vtt: null }) } }
  } else if (audio) {
    const m = /^data:([^;]+);base64,(.*)$/s.exec(audio)
    if (m) { mediaType = mediaType || m[1]; audio = m[2] }
    buf = Buffer.from(audio, 'base64')
  } else return { statusCode: 400, body: JSON.stringify({ vtt: null }) }
  if (!buf || buf.length > 24 * 1024 * 1024) return { statusCode: 200, body: JSON.stringify({ vtt: null }) }

  try {
    const fd = new FormData()
    fd.append('file', new Blob([buf], { type: mediaType || 'audio/mpeg' }), 'audio.mp3')
    fd.append('model', process.env.OPENAI_TRANSCRIBE_MODEL || 'whisper-1')
    fd.append('response_format', 'vtt')
    const res = await fetch('https://api.openai.com/v1/audio/transcriptions', {
      method: 'POST', headers: { authorization: `Bearer ${key}` }, body: fd,
    })
    const vtt = await res.text()
    return { statusCode: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ vtt: res.ok && /WEBVTT/.test(vtt) ? vtt : null }) }
  } catch {
    return { statusCode: 200, body: JSON.stringify({ vtt: null }) }
  }
}
