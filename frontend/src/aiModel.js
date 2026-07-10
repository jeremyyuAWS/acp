// The model that actually ran — never a brand name someone typed.
//
// ACP runs local Ollama models: a text model (OLLAMA_MODEL, default llama3.2) and a vision
// model (OLLAMA_VISION_MODEL, default llava:7b). Nothing is sent to a third party; there is no
// Anthropic or OpenAI client anywhere in api/. The UI nevertheless claimed "Claude vision" and
// "Whisper transcription" — the first names a service ACP never calls, the second names a
// pipeline that does not exist (nothing in api/ transcribes audio).
//
// That mattered most on the screens meant to earn a reviewer's trust: naming a model that did
// not run is worse than naming none, and it breaks the local-models-only promise outright.
//
// Both ids are already reported, per-deployment, by GET /ai/status. Read them from there; the
// operator can change the models with an env var and the UI must follow.

import { getAiStatus } from './api.js'

// Shown when the backend hasn't answered yet, or AI is off. Names no model — because we don't
// know one — rather than guessing a default that may not be what's deployed.
export const UNKNOWN_MODEL = 'local model'

export function modelLabel(status, kind = 'vision') {
  const id = kind === 'vision' ? status?.vision_model : status?.model
  return (typeof id === 'string' && id.trim()) ? id.trim() : UNKNOWN_MODEL
}

// True only when the backend says a vision model is actually pulled and reachable. Alt text
// degrades to human review without one, so the UI must not promise it.
export const visionReady = (status) => !!(status?.available && status?.vision_available)

let cached = null
export function loadAiModels() {
  if (!cached) cached = getAiStatus().then((s) => s || {}).catch(() => ({}))
  return cached
}

export function _resetForTests() { cached = null }
