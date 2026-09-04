import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const readPy = (f) => readFileSync(join(here, '../../api', f), 'utf8')

describe('P2 — Reviewer-behaviour → automation-mode migration (ADR 0019 §8.5)', () => {
  it('hitl_analytics SELECT includes ai_value and final_value', () => {
    const src = readPy('store.py')
    expect(src).toMatch(/ai_value.*final_value|final_value.*ai_value/)
  })

  it('store defines promotion thresholds as class constants', () => {
    const src = readPy('store.py')
    expect(src).toMatch(/_MATURITY_MIN_APPROVALS/)
    expect(src).toMatch(/_MATURITY_MAX_EDIT_RATE/)
    expect(src).toMatch(/_MATURITY_MIN_APPROVAL_RATE/)
  })

  it('hitl_analytics returns ready_to_promote per rule', () => {
    const src = readPy('store.py')
    expect(src).toMatch(/ready_to_promote/)
  })

  it('hitl_analytics returns promotable_rules at the top level', () => {
    const src = readPy('store.py')
    expect(src).toMatch(/promotable_rules/)
  })

  it('avg_edit_distance is computed via difflib SequenceMatcher', () => {
    const src = readPy('store.py')
    expect(src).toMatch(/difflib/)
    expect(src).toMatch(/SequenceMatcher/)
    expect(src).toMatch(/avg_edit_distance/)
  })

  it('promotion gate requires all three thresholds (approvals, edit_rate, approval_rate)', () => {
    const src = readPy('store.py')
    expect(src).toMatch(/_MATURITY_MIN_APPROVALS/)
    expect(src).toMatch(/_MATURITY_MAX_EDIT_RATE/)
    expect(src).toMatch(/_MATURITY_MIN_APPROVAL_RATE/)
    // All three referenced in the ready_to_promote assignment expression
    const marker = 'ready_to_promote"] = ('
    const pos = src.indexOf(marker)
    expect(pos).toBeGreaterThan(0)
    const block = src.slice(pos, pos + 400)
    expect(block).toMatch(/_MATURITY_MIN_APPROVALS/)
    expect(block).toMatch(/_MATURITY_MAX_EDIT_RATE/)
    expect(block).toMatch(/_MATURITY_MIN_APPROVAL_RATE/)
  })

  it('Remediate renders a promotion chip for each promotable_rules entry', () => {
    const src = read('Remediate.jsx')
    expect(src).toMatch(/promotable_rules/)
    expect(src).toMatch(/ready for AI-Assisted/)
  })

  it('promotion chip tooltip explains the three thresholds in plain language', () => {
    const src = read('Remediate.jsx')
    expect(src).toMatch(/≥10 approvals/)
    expect(src).toMatch(/≤20% edit rate/)
    expect(src).toMatch(/≥90% approval rate/)
  })

  it('promotion chip uses the success colour token, not a hard-coded hex', () => {
    const src = read('Remediate.jsx')
    expect(src).toMatch(/var\(--success-bg/)
    expect(src).toMatch(/var\(--success-fg/)
  })

  it('promotion chip points reviewer to Settings → Automation', () => {
    const src = read('Remediate.jsx')
    expect(src).toMatch(/Settings.*Automation/)
  })

  it('promotion signal is labelled rev-maturity in the DOM', () => {
    const src = read('Remediate.jsx')
    expect(src).toMatch(/rev-maturity/)
  })
})
