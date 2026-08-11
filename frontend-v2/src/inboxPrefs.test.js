import { describe, it, expect } from 'vitest'
import { inboxPrefsKey, loadInboxPrefs, saveInboxPrefs } from './inboxPrefs.js'

// A minimal Storage stand-in so these run without a DOM and can't leak between cases.
function fakeStore() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    _m: m,
  }
}

describe('inboxPrefs', () => {
  it('returns defaults when nothing is stored', () => {
    const s = fakeStore()
    expect(loadInboxPrefs('run1', s)).toEqual({ query: '', severity: null, criterion: null, groupByFile: false })
  })

  it('round-trips the view controls', () => {
    const s = fakeStore()
    saveInboxPrefs('run1', { query: 'contrast', severity: 'CRITICAL', criterion: '1.4.3', groupByFile: true }, s)
    expect(loadInboxPrefs('run1', s)).toEqual({ query: 'contrast', severity: 'CRITICAL', criterion: '1.4.3', groupByFile: true })
  })

  it('scopes prefs per scan — one run’s filter never bleeds into another', () => {
    const s = fakeStore()
    saveInboxPrefs('run1', { query: 'docx', groupByFile: true }, s)
    expect(inboxPrefsKey('run1')).not.toEqual(inboxPrefsKey('run2'))
    expect(loadInboxPrefs('run2', s)).toEqual({ query: '', severity: null, criterion: null, groupByFile: false })
  })

  it('falls back to defaults on corrupt JSON rather than throwing', () => {
    const s = fakeStore()
    s.setItem(inboxPrefsKey('run1'), '{not valid json')
    expect(loadInboxPrefs('run1', s)).toEqual({ query: '', severity: null, criterion: null, groupByFile: false })
  })

  it('coerces types — groupByFile is always boolean, empty facets become null', () => {
    const s = fakeStore()
    s.setItem(inboxPrefsKey('run1'), JSON.stringify({ query: 5, severity: '', criterion: undefined, groupByFile: 1 }))
    const p = loadInboxPrefs('run1', s)
    expect(p.query).toBe('')          // non-string query ignored
    expect(p.severity).toBe(null)
    expect(p.criterion).toBe(null)
    expect(p.groupByFile).toBe(true)  // truthy coerced to boolean
  })

  it('keys a null run id to a stable bucket instead of crashing', () => {
    const s = fakeStore()
    saveInboxPrefs(null, { query: 'x' }, s)
    expect(loadInboxPrefs(null, s).query).toBe('x')
    expect(inboxPrefsKey(null)).toBe('acp:inbox:none')
  })
})
