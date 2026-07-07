// Rule manifest and orchestrator.
//
// Each rule module exports:
//   meta   — { id, level, name, fixMode: 'auto'|'ai-assisted'|'human-only' }
//   check  — (doc: Document) => Array<{ element, detail, severity }>
//   fix    — (doc: Document) => Set<string>  (change descriptions)
//
// Add a new rule: create wcag-X-X-X.js alongside this file, import it here,
// and append it to allRules. No other file needs changing.

import * as r311  from './wcag-3-1-1.js'
import * as r242  from './wcag-2-4-2.js'
import * as r111  from './wcag-1-1-1.js'
import * as r131  from './wcag-1-3-1.js'
import * as r244  from './wcag-2-4-4.js'
import * as r143  from './wcag-1-4-3.js'
import * as r144  from './wcag-1-4-4.js'
import * as r1410 from './wcag-1-4-10.js'
import * as r243  from './wcag-2-4-3.js'
import * as r211  from './wcag-2-1-1.js'
import * as r141  from './wcag-1-4-1.js'
import * as r412  from './wcag-4-1-2.js'
import * as r1411 from './wcag-1-4-11.js'
import * as r1412 from './wcag-1-4-12.js'
import * as r246  from './wcag-2-4-6.js'
import * as r247  from './wcag-2-4-7.js'
import * as r314  from './wcag-3-1-4.js'
import * as r134  from './wcag-1-3-4.js'
import * as r135  from './wcag-1-3-5.js'
import * as r142  from './wcag-1-4-2.js'
import * as r146  from './wcag-1-4-6.js'
import * as r241  from './wcag-2-4-1.js'
import * as r253  from './wcag-2-5-3.js'
import * as r332  from './wcag-3-3-2.js'
import * as r121  from './wcag-1-2-1.js'
import * as r122  from './wcag-1-2-2.js'
import * as r123  from './wcag-1-2-3.js'
import * as r258  from './wcag-2-5-8.js'

// Ordered by WCAG SC number. Screen-reader-impacting checks run first.
export const allRules = [
  r111,  // 1.1.1 Non-text Content
  r121,  // 1.2.1 Audio-only & Video-only (Prerecorded)
  r122,  // 1.2.2 Captions (Prerecorded)
  r123,  // 1.2.3 Audio Description or Media Alternative
  r131,  // 1.3.1 Info and Relationships
  r134,  // 1.3.4 Orientation
  r135,  // 1.3.5 Identify Input Purpose
  r141,  // 1.4.1 Use of Color
  r142,  // 1.4.2 Audio Control
  r143,  // 1.4.3 Contrast (Minimum)
  r144,  // 1.4.4 Resize Text
  r146,  // 1.4.6 Contrast (Enhanced)
  r1410, // 1.4.10 Reflow
  r1411, // 1.4.11 Non-text Contrast
  r1412, // 1.4.12 Text Spacing
  r211,  // 2.1.1 Keyboard
  r241,  // 2.4.1 Bypass Blocks
  r242,  // 2.4.2 Page Titled
  r243,  // 2.4.3 Focus Order
  r244,  // 2.4.4 Link Purpose
  r246,  // 2.4.6 Headings and Labels
  r247,  // 2.4.7 Focus Visible
  r253,  // 2.5.3 Label in Name
  r258,  // 2.5.8 Target Size (Minimum)
  r311,  // 3.1.1 Language of Page
  r314,  // 3.1.4 Abbreviations
  r332,  // 3.3.2 Labels or Instructions
  r412,  // 4.1.2 Name, Role, Value
]

// Non-technical phrase per SC — mirrors the backend RULE_CATALOG.plain (api/store.py).
// Used so the in-app rule-coverage manifest reads like Grafana/Langfuse.
export const PLAIN_NAMES = {
  '1.1.1': 'Images missing a text description',
  '1.2.1': 'Audio/video with no transcript',
  '1.2.2': 'Video missing captions',
  '1.2.3': 'Video missing audio description or transcript',
  '1.3.1': 'Structure not marked up (headings, lists, tables)',
  '1.3.4': 'Content locked to one screen orientation',
  '1.3.5': "Form fields don't declare their purpose",
  '1.4.1': 'Information shown by color alone',
  '1.4.2': "Autoplaying media that can't be stopped",
  '1.4.5': 'Text baked into an image',
  '1.4.6': 'Text below the enhanced contrast ratio',
  '2.4.1': 'No way to skip repeated navigation',
  '2.5.3': "Control names don't match their visible labels",
  '2.5.8': 'Touch targets smaller than 24px',
  '3.3.2': 'Required fields with no label or instructions',
  '1.4.3': 'Text with low color contrast',
  '1.4.4': "Text that can't be enlarged",
  '1.4.10': "Content that doesn't reflow on small screens",
  '1.4.11': 'Buttons or icons with low contrast',
  '1.4.12': "Text spacing can't be adjusted",
  '2.1.1': "Can't be used with a keyboard",
  '2.4.2': 'Missing a page or document title',
  '2.4.3': 'Illogical keyboard navigation order',
  '2.4.4': "Unclear link text (e.g. 'click here')",
  '2.4.6': 'Unclear headings or labels',
  '2.4.7': 'No visible keyboard focus indicator',
  '3.1.1': 'Document language not set',
  '3.1.4': 'Unexplained abbreviations',
  '4.1.2': 'Controls missing names/roles for assistive tech',
}

// Run check() on every active rule and return a coverage manifest.
// When aiEnabled=false, ai-assisted rules are still checked (finding is reported)
// but their fixMode is surfaced as 'human-only' so callers can route to HITL.
//
// Returns: Array<{ rule: meta, findings: [], outcome: 'PASS'|'FAIL'|'SKIP' }>
export function runChecks(doc, { aiEnabled = true } = {}) {
  return allRules.map((mod) => {
    try {
      const findings = mod.check(doc)
      return {
        rule: { ...mod.meta, effectiveFixMode: !aiEnabled && mod.meta.fixMode === 'ai-assisted' ? 'human-only' : mod.meta.fixMode },
        findings,
        outcome: findings.length > 0 ? 'FAIL' : 'PASS',
      }
    } catch (err) {
      return { rule: mod.meta, findings: [], outcome: 'SKIP', skipReason: String(err) }
    }
  })
}

// Apply fix() from every fixable rule and return the union of change descriptions.
// When aiEnabled=false, only 'auto' rules run; 'ai-assisted' rules are skipped
// (their findings stay in the HITL queue).
//
// Returns: Array<string>
export function runFixes(doc, { aiEnabled = true } = {}) {
  const changes = new Set()
  allRules.forEach((mod) => {
    if (mod.meta.fixMode === 'human-only') return
    if (!aiEnabled && mod.meta.fixMode === 'ai-assisted') return
    try {
      mod.fix(doc).forEach((c) => changes.add(c))
    } catch {
      // individual rule failure should not abort the remediation run
    }
  })
  return [...changes]
}
