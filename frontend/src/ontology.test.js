import { describe, it, expect } from 'vitest'
import { evalRule, classifyFile, annotate, riskScore, riskFactors, parseNL, taxonomyPaths, worstSev, exposureOf, sensitivityOf } from './ontology.js'

const doc = (over = {}) => ({
  file: 'enrollment.pdf', department: 'Legal & Compliance', sourceName: 'Box', type: 'pdf',
  tags: ['public-facing', 'PII'], seniority: 'Director', ageDays: 600, views90d: 50, sizeKB: 200,
  status: 'issues', issues: [{ severity: 'CRITICAL' }, { severity: 'MODERATE' }], ...over,
})

const cond = (field, op, value) => ({ field, op, value })
const rule = (conditions, match = 'all', actions = {}) => ({ id: 'r', name: 'r', match, conditions, actions })

describe('field derivations', () => {
  it('exposure / sensitivity / worst severity', () => {
    expect(exposureOf(doc())).toBe('public-facing')
    expect(exposureOf(doc({ tags: ['high-traffic'] }))).toBe('high-traffic')
    expect(exposureOf(doc({ tags: [] }))).toBe('internal')
    expect(sensitivityOf(doc())).toBe('PII')
    expect(sensitivityOf(doc({ tags: ['legal-hold'] }))).toBe('legal-hold')
    expect(sensitivityOf(doc({ tags: [] }))).toBe('none')
    expect(worstSev(doc())).toBe('CRITICAL')
    expect(worstSev(doc({ issues: [{ severity: 'MINOR' }] }))).toBe('MINOR')
    expect(worstSev(doc({ issues: [] }))).toBe('none')
  })
})

describe('evalRule operators', () => {
  const f = doc()
  it('string ops', () => {
    expect(evalRule(f, rule([cond('department', 'is', 'Legal & Compliance')]))).toBe(true)
    expect(evalRule(f, rule([cond('department', 'is', 'Finance')]))).toBe(false)
    expect(evalRule(f, rule([cond('department', 'is not', 'Finance')]))).toBe(true)
    expect(evalRule(f, rule([cond('type', 'is', 'pdf')]))).toBe(true)
    expect(evalRule(f, rule([cond('filename', 'contains', 'enroll')]))).toBe(true)
    expect(evalRule(f, rule([cond('filename', 'starts with', 'enroll')]))).toBe(true)
    expect(evalRule(f, rule([cond('filename', 'matches regex', '\\.pdf$')]))).toBe(true)
  })
  it('tag ops', () => {
    expect(evalRule(f, rule([cond('tag', 'has', 'PII')]))).toBe(true)
    expect(evalRule(f, rule([cond('tag', 'has', 'legal-hold')]))).toBe(false)
    expect(evalRule(f, rule([cond('tag', 'does not have', 'legal-hold')]))).toBe(true)
  })
  it('derived + numeric + severity ops', () => {
    expect(evalRule(f, rule([cond('exposure', 'is', 'public-facing')]))).toBe(true)
    expect(evalRule(f, rule([cond('sensitivity', 'is', 'PII')]))).toBe(true)
    expect(evalRule(f, rule([cond('ageDays', 'older than', '540')]))).toBe(true)
    expect(evalRule(f, rule([cond('ageDays', 'newer than', '540')]))).toBe(false)
    expect(evalRule(f, rule([cond('views90d', 'less than', '60')]))).toBe(true)
    expect(evalRule(f, rule([cond('views90d', 'greater than', '60')]))).toBe(false)
    expect(evalRule(f, rule([cond('severity', 'is at least', 'SERIOUS')]))).toBe(true)
    expect(evalRule(f, rule([cond('severity', 'is at least', 'CRITICAL')]))).toBe(true)
  })
  it('match all vs any', () => {
    const a = cond('type', 'is', 'pdf'); const b = cond('department', 'is', 'Finance')
    expect(evalRule(f, rule([a, b], 'all'))).toBe(false)
    expect(evalRule(f, rule([a, b], 'any'))).toBe(true)
    expect(evalRule(f, rule([], 'all'))).toBe(false) // no conditions never matches
  })
})

describe('classifyFile + annotate', () => {
  const pub = {
    labels: [{ id: 'l1', name: 'Contracts', color: '#111' }],
    rules: [
      rule([cond('type', 'is', 'pdf'), cond('exposure', 'is', 'public-facing')], 'all', { priority: 'Critical', slaDays: 30, label: 'l1', category: 'Legal / Contracts' }),
      rule([cond('department', 'is', 'Legal & Compliance')], 'all', { priority: 'High', slaDays: 45 }),
    ],
  }
  it('returns first-match classification with label/category/sla', () => {
    const c = classifyFile(doc(), pub)
    expect(c.priority).toBe('Critical')
    expect(c.sla).toBe(30)
    expect(c.category).toBe('Legal / Contracts')
    expect(c.label).toMatchObject({ id: 'l1', name: 'Contracts' })
    expect(c.score).toBeGreaterThan(0)
  })
  it('first matching rule wins', () => {
    // a docx in Legal skips rule 1 (type≠pdf) and hits rule 2
    const c = classifyFile(doc({ type: 'docx', tags: [] }), pub)
    expect(c.priority).toBe('High')
    expect(c.sla).toBe(45)
    expect(c.label).toBeNull()
  })
  it('null when nothing matches or nothing published', () => {
    expect(classifyFile(doc({ type: 'xlsx', department: 'Finance', tags: [] }), pub)).toBeNull()
    expect(classifyFile(doc(), null)).toBeNull()
    expect(classifyFile(doc(), { rules: [] })).toBeNull()
  })
  it('annotate tags files and is identity-safe with no ontology', () => {
    const files = [doc(), doc({ type: 'xlsx', department: 'Finance', tags: [] })]
    const out = annotate(files, pub)
    expect(out[0].ont.priority).toBe('Critical')
    expect(out[1].ont).toBeNull()
    expect(annotate(files, null)).toBe(files) // unchanged reference
  })
})

describe('weighted risk score', () => {
  it('multiplies severity × criticality × exposure × regulatory × usage', () => {
    const fac = riskFactors(doc(), 'Critical')
    expect(fac.severity).toBe(4) // CRITICAL
    expect(fac.criticality).toBe(4) // Critical priority
    expect(fac.exposure).toBe(3) // public-facing
    expect(fac.regulatory).toBe(3) // PII
    expect(fac.usage).toBeGreaterThanOrEqual(1)
    expect(riskScore(doc(), 'Critical')).toBeCloseTo(fac.severity * fac.criticality * fac.exposure * fac.regulatory * fac.usage, 5)
  })
  it('lower-risk doc scores lower', () => {
    const low = doc({ tags: [], issues: [{ severity: 'MINOR' }], views90d: 2 })
    expect(riskScore(low, 'Low')).toBeLessThan(riskScore(doc(), 'Critical'))
  })
})

describe('natural-language parser', () => {
  it('externally published PDFs owned by Legal → conditions', () => {
    const r = parseNL('Prioritize all externally published PDF documents owned by Legal as Critical', { department: ['Legal & Compliance', 'Finance'] })
    const has = (field, value) => r.conditions.some((c) => c.field === field && c.value === value)
    expect(has('exposure', 'public-facing')).toBe(true)
    expect(has('type', 'pdf')).toBe(true)
    expect(has('department', 'Legal & Compliance')).toBe(true)
    expect(r.actions.priority).toBe('Critical')
  })
  it('archived → older-than rule, low priority', () => {
    const r = parseNL('Archived marketing materials are Low priority', { department: [] })
    expect(r.conditions.some((c) => c.field === 'ageDays' && c.op === 'older than')).toBe(true)
    expect(r.actions.priority).toBe('Low')
  })
})

describe('taxonomyPaths', () => {
  it('flattens to slash-joined paths', () => {
    const paths = taxonomyPaths({ name: 'Corp', children: [{ name: 'Legal', children: [{ name: 'Contracts' }] }, { name: 'HR' }] })
    expect(paths).toEqual(['Corp', 'Corp / Legal', 'Corp / Legal / Contracts', 'Corp / HR'])
  })
})
