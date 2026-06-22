// Real AI remediation for the text-based, AI-assisted criteria. The browser POSTs
// { kind, text, context }; this calls Claude (key server-side) and returns { fix }.
// kinds: 'link' (2.4.4 link purpose), 'sensory' (1.3.3 sensory characteristics),
// 'language-parts' (3.1.2 language of parts). Graceful null fallback with no key.
const PROMPTS = {
  link: {
    system: 'You rewrite vague hyperlink text ("click here", "read more", "learn more") into concise, descriptive link text that makes sense out of context, for screen-reader users (WCAG 2.4.4). Output ONLY the new link text — at most ~8 words, no surrounding quotes, no preamble.',
    user: (b) => `Existing link text: "${b.text}". Surrounding context: ${b.context || 'a page on the site'}. Write better link text.`,
  },
  sensory: {
    system: 'You rewrite instructions that rely on shape, size, visual location or sound ("click the round button on the right") so they identify the control by its name or label instead, while keeping any positional hint as secondary (WCAG 1.3.3). Output ONLY the rewritten instruction.',
    user: (b) => `Instruction: "${b.text}". Rewrite it so it does not depend on shape/size/position/sound alone.`,
  },
  'language-parts': {
    system: 'You find passages within a mostly-English text that are written in another language and would need a lang attribute for correct screen-reader pronunciation (WCAG 3.1.2). Output a short plain-text list, one per line, as: <passage> → <ISO 639-1 code>. If there are none, output exactly: none',
    user: (b) => `Text:\n${String(b.text || '').slice(0, 2000)}`,
  },
}

export async function handler(event) {
  if (event.httpMethod !== 'POST') return { statusCode: 405, body: 'Method not allowed' }
  const key = process.env.ANTHROPIC_API_KEY
  if (!key) return { statusCode: 200, body: JSON.stringify({ fix: null }) }

  let body = {}
  try { body = JSON.parse(event.body || '{}') } catch { /* ignore */ }
  const p = PROMPTS[body.kind]
  if (!p || !body.text) return { statusCode: 400, body: JSON.stringify({ fix: null }) }

  try {
    const res = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({
        model: process.env.ANTHROPIC_MODEL || 'claude-opus-4-8',
        max_tokens: 220,
        system: p.system,
        messages: [{ role: 'user', content: p.user(body) }],
      }),
    })
    const data = await res.json()
    let fix = data?.content?.[0]?.text?.trim() || null
    if (fix) fix = fix.replace(/^["“]|["”]$/g, '').trim()
    return { statusCode: 200, headers: { 'content-type': 'application/json' }, body: JSON.stringify({ fix, model: data?.model || null }) }
  } catch {
    return { statusCode: 200, body: JSON.stringify({ fix: null }) }
  }
}
