// Parse the fg/bg colours + measured ratio out of a contrast finding's detail string, so the
// review card can render the actual low-contrast text as VISUAL evidence (HITL vision: verify in
// <10s, not read a number). The producer (api/office_structure.pptx_contrast_checks, and xlsx once
// normalised) emits a stable shape: "Text #RRGGBB on #RRGGBB is X.X:1 (needs Y.Y:1)". Returns null
// when the detail carries no colours (html/pdf heuristics) — the card then keeps its prose, no swatch.
const RE = /#([0-9a-fA-F]{6})\s+on\s+#([0-9a-fA-F]{6})\s+is\s+([\d.]+):1\s*\(needs\s+([\d.]+):1\)/

export function parseContrast(detail) {
  const m = RE.exec(String(detail || ''))
  if (!m) return null
  const ratio = parseFloat(m[3])
  const needs = parseFloat(m[4])
  if (!(ratio > 0) || !(needs > 0)) return null
  return { fg: '#' + m[1].toUpperCase(), bg: '#' + m[2].toUpperCase(), ratio, needs,
           passes: ratio >= needs }
}
