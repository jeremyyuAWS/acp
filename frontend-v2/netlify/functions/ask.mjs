// Optional serverless endpoint for free-form chat questions. The browser POSTs
// { question, context } (context = a JSON summary of the scan); this calls Claude
// with the key kept server-side and returns { answer }.
//
// To enable: set ANTHROPIC_API_KEY in Netlify env (and optionally ANTHROPIC_MODEL).
// With no key it returns { answer: null } and the client uses its synthetic fallback,
// so the demo works either way.
export async function handler(event) {
  if (event.httpMethod !== 'POST') return { statusCode: 405, body: 'Method not allowed' }
  const key = process.env.ANTHROPIC_API_KEY
  if (!key) return { statusCode: 200, body: JSON.stringify({ answer: null }) }

  let body = {}
  try { body = JSON.parse(event.body || '{}') } catch { /* ignore */ }
  const { question, context } = body
  if (!question) return { statusCode: 400, body: JSON.stringify({ answer: null }) }

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: process.env.ANTHROPIC_MODEL || 'claude-haiku-4-5-20251001',
        max_tokens: 320,
        system: 'You are a compliance analyst assistant for a WCAG 2.1 accessibility platform. Answer concisely (1-3 sentences) using the provided JSON scan summary, citing exact numbers when relevant. If the data does not contain the answer, give a brief, realistic, helpful response from general accessibility-compliance knowledge. Do not invent specific document names.',
        messages: [{ role: 'user', content: `Scan summary (JSON): ${JSON.stringify(context)}\n\nQuestion: ${question}` }],
      }),
    })
    const data = await res.json()
    const answer = data?.content?.[0]?.text || null
    return { statusCode: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ answer }) }
  } catch {
    return { statusCode: 200, body: JSON.stringify({ answer: null }) }
  }
}
