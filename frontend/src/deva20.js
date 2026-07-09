// Deva's "20-check document core" — the criteria the customer actually certifies against.
//
//   87 WCAG 2.2 criteria  →  50 US-regulated (A/AA)  →  20 that apply to documents
//
// Single source of truth. The Assess coverage table and the file drawer's coverage table
// must agree on exactly which 20 those are; a second hand-maintained copy would drift and
// two screens would quietly disagree about what was certified.
//
// Grouped as the customer's own standard slide groups them.
export const DEVA_20 = new Set([
  // Structure & reading order
  '1.1.1', '1.3.1', '1.3.2', '1.3.3', '2.4.6',
  // Text & language
  '3.1.1', '3.1.2', '1.4.4', '1.4.5', '1.4.10', '1.4.12',
  // Color & contrast
  '1.4.1', '1.4.3', '1.4.11',
  // Navigation & interactive
  '2.4.2', '2.4.3', '2.4.4', '2.1.1', '2.1.2', '4.1.2',
])
