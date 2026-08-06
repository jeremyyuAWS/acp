// LLM-powered executive narrative for the per-document conformance report.
// The browser POSTs { file, score, finalScore, engine, findings:[{wcag,sev,detail}] };
// Claude (key server-side) returns a structured, document-specific summary that makes
// the PDF read like an expert wrote it. Graceful null fallback with no key.
export async function handler(event) {
  if (event.httpMethod !== 'POST') return { statusCode: 405, body: 'Method not allowed' }
  const key = process.env.ANTHROPIC_API_KEY
  if (!key) return { statusCode: 200, body: JSON.stringify({ insight: null }) }

  let body = {}
  try { body = JSON.parse(event.body || '{}') } catch { /* ignore */ }
  const { file = 'document', score, finalScore, engine, findings = [] } = body
  const list = findings.slice(0, 20).map((f) => `- ${f.wcag} (${(f.sev || '').toLowerCase()}): ${f.detail}`).join('\n') || '- none'

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: process.env.ANTHROPIC_MODEL || 'claude-opus-4-8',
        max_tokens: 700,
        system: 'You are a senior digital-accessibility consultant writing the executive summary of a single-document WCAG 2.1 AA conformance report for organizational leadership. Be specific to the actual findings, precise, and professional — confident but never alarmist, and never invent findings. Return ONLY a compact JSON object with four string fields: "headline" (a one-line verdict, <= 90 chars), "summary" (2-3 sentences: the document\'s accessibility posture as received and what remediation achieved), "impact" (1-2 sentences naming which users were affected and how — e.g. screen-reader, low-vision, keyboard-only users), "recommendation" (one sentence on what to do next / how to keep it compliant).',
        messages: [{ role: 'user', content: `Document: "${file}"\nAssessed by: ${engine || 'WCAG 2.1 AA engine'}\nScore as received: ${score}/100 → after remediation: ${finalScore}/100\nFindings:\n${list}\n\nReturn the JSON.` }],
      }),
    })
    const data = await res.json()
    const raw = data?.content?.[0]?.text?.trim() || ''
    let insight = null
    try { insight = JSON.parse(raw.replace(/^```json\s*|\s*```$/g, '')) } catch { /* fall back */ }
    if (insight && typeof insight === 'object') {
      const clean = (s) => (typeof s === 'string' ? s.replace(/\s+/g, ' ').trim() : '')
      insight = { headline: clean(insight.headline), summary: clean(insight.summary), impact: clean(insight.impact), recommendation: clean(insight.recommendation) }
    }
    return { statusCode: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ insight, model: data?.model || null }) }
  } catch {
    return { statusCode: 200, body: JSON.stringify({ insight: null }) }
  }
}
