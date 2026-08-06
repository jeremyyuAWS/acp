// The SPA must render the scope the SERVER is gating on, not a preset compiled into the bundle.
//
// Before applyScopeConfig() existed, activeScope.js declared `const ACTIVE_SCOPE_PRESET =
// 'deva-final'`. Changing the backend's `scan_scope` setting moved the server's gate while every
// denominator, "N of 20 in scope" line and out-of-scope note in the UI went on describing the
// build's preset — two sources of truth for one question, and the wrong one was the one the
// customer could see.
//
// Each test re-imports the module so it starts from the untouched fallback: applyScopeConfig
// mutates module state by design (live bindings are what let consumers see the update without
// threading a prop through ten components).
import { describe, it, expect, beforeEach, vi } from 'vitest'

let A
beforeEach(async () => {
  // applyScopeConfig mutates module state by design — live bindings are what let consumers see
  // the update without threading a prop through ten components. Resetting the registry gives
  // each test the untouched fallback, so one test's narrowing cannot leak into the next.
  vi.resetModules()
  A = await import('./activeScope.js')
})

describe('the pre-fetch fallback', () => {
  it('is the value the file used to hard-code, so first paint is unchanged', () => {
    expect(A.ACTIVE_SCOPE_PRESET).toBe('deva-final')
    expect(A.SCOPE_SIZE).toBe(A.SCOPE_SCS.size)
    expect(A.SCOPE_SIZE).toBeGreaterThan(0)
  })

  it('is a subset of the document core, or every "of the 20" sentence is false', () => {
    expect(A.SCOPE_IS_SUBSET_OF_CORE).toBe(true)
  })
})

describe('applyScopeConfig — a narrowing reported by the server', () => {
  it('replaces the criteria, the size, and the denominator the UI renders', () => {
    const changed = A.applyScopeConfig({
      scope: { name: 'custom', criteria: { '1.1.1': ['docx'], '1.4.3': ['docx', 'pdf'] } },
    })
    expect(changed).toBe(true)
    expect(A.ACTIVE_SCOPE_PRESET).toBe('custom')
    expect([...A.SCOPE_SCS].sort()).toEqual(['1.1.1', '1.4.3'])
    expect(A.SCOPE_SIZE).toBe(2)
    expect(A.DENOMINATOR.scope.total).toBe(2)
    expect(A.DENOMINATOR.scope.question).toContain('2 criteria')
  })

  it('recomputes what falls OUTSIDE the scope, so the out-of-scope note stays arithmetically true', () => {
    A.applyScopeConfig({ scope: { name: 'custom', criteria: { '1.1.1': ['docx'] } } })
    expect(A.OUT_OF_SCOPE_SCS.has('1.1.1')).toBe(false)
    expect(A.OUT_OF_SCOPE_SCS.size).toBe(A.CORE_SCS.size - 1)
    expect(A.outOfScopeNote()).toContain(`${A.CORE_SCS.size - 1} of the ${A.CORE_SCS.size}`)
  })

  it('gates per (criterion, format), mirroring the backend in_scope()', () => {
    A.applyScopeConfig({ scope: { name: 'custom', criteria: { '2.1.1': ['pptx', 'pdf'] } } })
    expect(A.inScopeFmt('2.1.1', 'pptx')).toBe(true)
    expect(A.inScopeFmt('2.1.1', 'docx')).toBe(false)
    expect(A.inScopeFmt('1.1.1', 'docx')).toBe(false)     // criterion not in scope at all
  })

  it('never excludes an unparseable format — the gate honours a choice, it does not invent one', () => {
    A.applyScopeConfig({ scope: { name: 'custom', criteria: { '2.1.1': ['pptx'] } } })
    expect(A.inScopeFmt('2.1.1', null)).toBe(true)
  })
})

describe('applyScopeConfig — no restriction', () => {
  it('criteria:null means EVERY criterion is in scope, not none', () => {
    // The dangerous misreading: treating "no scope set" as an empty scope would render
    // "0 of 20 criteria in scope" — the most alarming possible way to fail.
    A.applyScopeConfig({ scope: { name: '', criteria: null } })
    expect(A.SCOPE_SIZE).toBe(A.CORE_SCS.size)
    expect(A.OUT_OF_SCOPE_SCS.size).toBe(0)
    expect(A.inScopeFmt('2.1.1', 'docx')).toBe(true)
  })
})

describe('applyScopeConfig — bad input keeps the fallback', () => {
  const before = () => ({ preset: A.ACTIVE_SCOPE_PRESET, size: A.SCOPE_SIZE })

  it.each([
    ['no config', undefined],
    ['no scope field', {}],
    ['scope not an object', { scope: 'deva-final' }],
    ['empty criteria map', { scope: { name: 'x', criteria: {} } }],
  ])('%s leaves the scope untouched and reports no change', (_label, cfg) => {
    const b = before()
    expect(A.applyScopeConfig(cfg)).toBe(false)
    expect(A.ACTIVE_SCOPE_PRESET).toBe(b.preset)
    expect(A.SCOPE_SIZE).toBe(b.size)
  })
})

describe('change detection', () => {
  it('reports false when the server confirms the scope already in force', () => {
    const criteria = {}
    for (const sc of A.SCOPE_SCS) criteria[sc] = ['docx']
    expect(A.applyScopeConfig({ scope: { name: 'deva-final', criteria } })).toBe(false)
  })
})
