// Client bridge to the serverless AI endpoints in frontend/netlify/functions/.
//
// These are REAL and they DO run — on the Netlify deployment of this SPA, where alt-text,
// ai-fix and insights POST to api.anthropic.com and transcribe POSTs to api.openai.com
// (keys supplied via Netlify env). The browser never sees a key.
//
// On the Azure ACP deployment the Dockerfile never ships netlify/, so /.netlify/functions/*
// 404s and every call here degrades to null; ACP's own AI is the local Ollama model in
// api/ai.py. Same SPA, two very different AI backends.
//
// Therefore NOTHING here may be labelled with a hardcoded model name. Each function returns
// the model that actually answered, and the UI renders that — see aiModel.js.
//
// Reached ONLY through aiRemote.js, which gates this module behind SIM so the Azure build
// never bundles it. Pure helpers (blobToBase64, allOfficeImages) moved to mediaExtract.js.

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
    // `model` is whatever answered (e.g. claude-opus-4-8). The badge renders it verbatim.
    return { alt: j?.alt || null, text: j?.text || null, model: j?.model || null }
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
    return j?.vtt ? { vtt: j.vtt, model: j?.model || null } : null
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
    // provider marks this as a THIRD-PARTY call, so the report never claims otherwise.
    return j?.insight ? { ...j.insight, model: j?.model || null, provider: 'anthropic' } : null
  } catch { return null }
}
