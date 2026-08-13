// Phase 2 — Human-in-the-loop pre-screen.
// Static detectors that FLAG the runtime / interactive / media risks for the Required
// A/AA criteria that can't be confirmed or auto-fixed without rendering or interaction.
// Each item is ROUTED to a human reviewer, never auto-remediated — the honest
// "detect & route" half of the two-axis triage model. The detail always says what a
// human must confirm, because static analysis can only surface the risk, not the verdict.
export function prescreenHtml(text) {
  if (!text) return []
  const out = []
  const seen = new Set()
  const flag = (wcag, sev, detail) => { if (seen.has(wcag)) return; seen.add(wcag); out.push({ wcag, sev, detail, route: 'human', auto: false }) }
  let doc
  try { doc = new DOMParser().parseFromString(text, 'text/html') } catch { return [] }
  const has = (re) => re.test(text)

  // 1.2.4 / 1.2.5 — live captions & audio description for media (human-produced)
  const vid = [...doc.querySelectorAll('video')]
  if (vid.some((v) => !v.querySelector('track[kind="captions"]')) || doc.querySelector('audio[autoplay]')) {
    flag('1.2.4 captions (live)', 'SERIOUS', 'media without a captions track — a human confirms synchronized captions.')
  }
  if (vid.some((v) => !v.querySelector('track[kind="descriptions"]'))) {
    flag('1.2.5 audio description', 'SERIOUS', 'video without an audio-description track — needs human-produced description.')
  }
  // 1.4.13 — content on hover or focus (tooltips / popovers)
  if (doc.querySelector('[title]') || has(/:hover|mouseover|tooltip|popover/i)) {
    flag('1.4.13 content on hover/focus', 'MODERATE', 'tooltip / hover content — a human confirms it is dismissable, hoverable and persistent.')
  }
  // 2.1.4 — single-character key shortcuts
  if (has(/onkeydown|onkeypress|addEventListener\(\s*['"]key/i)) {
    flag('2.1.4 character key shortcuts', 'MODERATE', 'key handlers detected — confirm single-key shortcuts can be turned off or remapped.')
  }
  // 2.2.1 / 2.2.2 — timing & moving / auto-updating content
  if (has(/setInterval|setTimeout|<marquee|<blink|requestAnimationFrame|animation\s*:/i)) {
    flag('2.2.2 pause, stop, hide', 'SERIOUS', 'timed or moving content — confirm it can be paused, stopped or hidden and time limits adjusted.')
  }
  // 2.5.1 / 2.5.2 / 2.5.4 — pointer gestures, cancellation, motion actuation
  if (has(/ontouchstart|gesturestart|deviceorientation|devicemotion|ondrag\b|pointer(down|move)/i)) {
    flag('2.5.1 pointer gestures', 'MODERATE', 'gesture / motion handlers — confirm a single-pointer, cancellable, no-motion alternative.')
  }
  // 3.2.1 / 3.2.2 — change of context on focus or input
  if (has(/onfocus=|onchange=|onblur=/i)) {
    flag('3.2.2 on focus / input', 'MODERATE', 'focus / input handlers — confirm no unexpected change of context occurs.')
  }
  // 3.3.1 / 3.3.3 / 3.3.4 — error identification, suggestion, prevention
  if ([...doc.querySelectorAll('form')].some((f) => !f.querySelector('[aria-invalid], [role="alert"], .error, [aria-describedby]'))) {
    flag('3.3.1 error identification', 'SERIOUS', 'form has no error-identification structure — confirm errors are announced, suggested and (legal/financial) reversible.')
  }
  // 4.1.3 — status messages
  if (doc.querySelector('form, button, [onclick]') && !doc.querySelector('[aria-live], [role="status"], [role="alert"], [role="log"]')) {
    flag('4.1.3 status messages', 'MODERATE', 'no live region — confirm dynamic status updates (saved, errors) are announced to assistive tech.')
  }
  return out
}
