// Screen-reader audio preview — hear a fix the way a blind user would.
//
// Trust is highest when a reviewer can VERIFY a fix, not just read a claim about it. This
// plays a value (alt text, a heading, a link) through the browser's built-in speech synthesis
// (Web Speech API) with the announcement a screen reader would prepend — "Image, …",
// "Heading level 2, …", "Link, …" — so the reviewer judges by ear whether the AI's
// description actually conveys the thing. Entirely LOCAL and private: the Web Speech API runs
// on the device, nothing is sent to a server, no model download, no cost.

export const srSupported = () =>
  typeof window !== 'undefined' && 'speechSynthesis' in window &&
  typeof window.SpeechSynthesisUtterance !== 'undefined'

// How a screen reader frames each kind of value before reading it aloud. Approximate but
// faithful to the common NVDA/VoiceOver phrasing — the point is the reviewer hears the value
// IN CONTEXT (as content, not as raw text), which is exactly what they're certifying.
const ROLE_LEAD = {
  '1.1.1': (v) => `Image. ${v}`,
  '2.4.6': (v) => `Heading. ${v}`,
  '2.4.10': (v) => `Heading. ${v}`,
  '2.4.4': (v) => `Link. ${v}`,
  '2.4.9': (v) => `Link. ${v}`,
  '2.4.2': (v) => `Document title. ${v}`,
}

export const srPhrase = (sc, value) => {
  const v = (value || '').trim()
  if (!v) return ''
  const lead = ROLE_LEAD[sc]
  return lead ? lead(v) : v
}

let current = null

// Speak `value` as a screen reader would announce it for success-criterion `sc`. Cancels any
// in-flight speech first (one preview at a time). Returns false when unsupported or empty, so
// the caller can hide the control. onEnd/onStart let the UI reflect the playing state.
export function speakAsScreenReader(sc, value, { onStart, onEnd, rate = 1 } = {}) {
  if (!srSupported()) return false
  const text = srPhrase(sc, value)
  if (!text) return false
  try {
    window.speechSynthesis.cancel()
    const u = new window.SpeechSynthesisUtterance(text)
    u.rate = rate
    u.onstart = () => { current = u; onStart && onStart() }
    u.onend = () => { current = null; onEnd && onEnd() }
    u.onerror = () => { current = null; onEnd && onEnd() }
    window.speechSynthesis.speak(u)
    return true
  } catch {
    return false
  }
}

export function stopSpeaking() {
  if (!srSupported()) return
  try { window.speechSynthesis.cancel() } catch { /* ignore */ }
  current = null
}

export const isSpeaking = () => !!current
