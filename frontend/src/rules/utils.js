// Shared utilities used by rule modules.

export function isLight(hex) {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16)
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.62
}

export function altFromSrc(src) {
  if (!src) return 'descriptive image'
  const base = src.split('/').pop().replace(/\.[^.]+$/, '').replace(/[-_]+/g, ' ').trim()
  return base ? `image: ${base}` : 'descriptive image'
}

// Known abbreviation → full expansion
export const ABBR = {
  WCAG: 'Web Content Accessibility Guidelines',
  ADA: 'Americans with Disabilities Act',
  PDF: 'Portable Document Format',
  PPO: 'Preferred Provider Organization',
  HDHP: 'High-Deductible Health Plan',
  FSA: 'Flexible Spending Account',
  HSA: 'Health Savings Account',
  FAQ: 'Frequently Asked Questions',
  PII: 'Personally Identifiable Information',
  UTSW: 'UT Southwestern',
  HR: 'Human Resources',
}

// Ambiguous link text patterns that must be rewritten.
export const AMBIGUOUS_LINK = /^(click here|read more|learn more|here|more)\.?$/i
