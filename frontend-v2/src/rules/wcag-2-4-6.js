// 2.4.6 Headings and Labels (Level AA)
// Headings and labels describe topic or purpose.
// Check: skipped heading levels (e.g. h1 → h3). A gap means the outline a screen-reader
//   user navigates by claims a nesting depth the document doesn't have, so the heading
//   no longer identifies which section it opens.
// Fix: clamp any level that jumps by more than one down to prev+1, so the outline has
//   no gaps and a re-scan clears.
//
// This module used to promote visually-styled pseudo-headings instead. That check was a
// 1.3.1 Info and Relationships failure filed under the wrong criterion — the element was
// not a heading at all, so 2.4.6's "do headings describe their topic" had nothing to judge
// — and it disagreed with docx, which files the identical signal under 1.3.1
// (office_structure.DOCX_PSEUDO_HEADING). It now lives on the backend as
// scanner.HTML_PSEUDO_HEADING / remediate._fix_pseudo_headings, under 1.3.1, so the two
// formats agree. What replaced it here mirrors scanner.HTML_HEADING_SKIP and
// remediate._fix_heading_skip, which is what 2.4.6 on html actually checks.
//
// NOTE (ADR 0023 audit, Correction 2): a clean result here is NOT a certified pass. Level
// well-formedness is not descriptiveness, so html 2.4.6 assesses on the 🟡 review lane
// (capability.js ASSESSMENT_FALLBACK.html['2.4.6'] === 'review'). fixMode stays 'auto'
// because the renumbering itself is deterministic — the two axes are independent.

export const meta = {
  id: '2.4.6',
  level: 'AA',
  name: 'Headings and Labels',
  fixMode: 'auto', // clamping a level gap is deterministic from the outline alone
}

const HEADINGS = 'h1, h2, h3, h4, h5, h6'
const levelOf = (el) => parseInt(el.tagName[1], 10)

export function check(doc) {
  const findings = []
  let prev = 0
  // EVERY gap is reported, not just the first — the fix closes them all in one pass, so
  // stopping early would leave the page looking one edit from clean when it was several.
  // `prev` advances to the level actually in the document (not the clamped prev+1), which
  // keeps h1→h3→h4 a single finding: the h3→h4 step is well-formed.
  doc.querySelectorAll(HEADINGS).forEach((el, i) => {
    const level = levelOf(el)
    if (prev > 0 && level > prev + 1) {
      findings.push({
        element: el.outerHTML.slice(0, 120),
        // The ordinal keeps two identical gaps (two separate h1→h3s) distinguishable.
        detail: `Heading ${i + 1}: level jumps from h${prev} to h${level} (should step to h${prev + 1})`,
        severity: 'MODERATE',
      })
    }
    prev = level
  })
  return findings
}

export function fix(doc) {
  const changes = new Set()
  let prev = 0
  doc.querySelectorAll(HEADINGS).forEach((el) => {
    let level = levelOf(el)
    if (prev > 0 && level > prev + 1) {
      level = prev + 1
      const h = doc.createElement(`h${level}`)
      h.innerHTML = el.innerHTML
      for (const a of [...el.attributes]) h.setAttribute(a.name, a.value)
      el.replaceWith(h)
      changes.add('Renumbered skipped heading levels so the outline has no gaps · 2.4.6')
    }
    prev = level
  })
  return changes
}
