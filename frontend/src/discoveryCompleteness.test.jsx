import { describe, it, expect } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import DiscoveryCompleteness from './DiscoveryCompleteness.jsx'
import { discoveredCount, enumerationMethod, previousListing } from './discoveryCompleteness.js'

// "Is this the whole estate?" — Discovery's own answer about its own completeness.
//
// Grounded in issue #333, which measured the failure on prod: 178 files uploaded, 39 discovered,
// presented as complete. The index returned 157 five minutes later. Nothing on the screen
// distinguished that from a genuinely small estate, and everything downstream — coverage, the
// reconciliation, the compliance assertion — is a fraction of a number that was wrong.

const text = (node) => renderToStaticMarkup(node)
  .replace(/<[^>]+>/g, ' ').replace(/&#x27;|&#39;/g, "'").replace(/&amp;/g, '&')
  .replace(/&quot;/g, '"').replace(/&#x2F;/g, '/').replace(/\s+/g, ' ').trim()

const RUN = (source, discovered, extra = {}) => ({
  id: 'now', source, completed_at: '2026-08-21T00:00:00Z',
  scope: { inventory: { discovered } }, ...extra,
})
const PRIOR = (source, discovered, id = 'old') => ({
  id, source, completed_at: '2026-08-20T00:00:00Z', scope: { inventory: { discovered } },
})

describe('the count it compares is the DISCOVERY count', () => {
  it('reads scope.inventory.discovered, not files', () => {
    // These drifted apart in #550: `files` now counts what ASSESS enqueued. Comparing it across
    // runs would compare a filtered count against an unfiltered one and report the FILTER as a
    // change in the estate — a true number producing a false claim.
    expect(discoveredCount({ scope: { inventory: { discovered: 12408 } }, files: 22 })).toBe(12408)
  })

  it('returns null rather than zero when there is no inventory', () => {
    expect(discoveredCount({ files: 22 })).toBeNull()
    expect(discoveredCount(null)).toBeNull()
  })
})

describe('what each source actually guarantees', () => {
  it('names the mechanism for an index-backed source, not a generic maybe', () => {
    // Verified at api/scanner.py:951,956 — SharePoint and OneDrive use Graph search(q=''), which
    // reads the search index. "May be incomplete" is true of everything and warns nobody; naming
    // the mechanism lets a reader tell whether it applies to them today.
    const m = enumerationMethod('sharepoint')
    expect(m.consistent).toBe(false)
    expect(m.caveat).toMatch(/search index/i)
    expect(m.resolve).toMatch(/list it again/i)
  })

  it('does not warn about a source that is immediately consistent', () => {
    // api/scanner.py:509 — Drive walks folders directly.
    const m = enumerationMethod('drive')
    expect(m.consistent).toBe(true)
    expect(m.resolve).toBeNull()
  })

  it('says nothing at all about a source it has not established', () => {
    expect(enumerationMethod('smb')).toBeNull()
    expect(enumerationMethod(undefined)).toBeNull()
  })
})

describe('this listing against the last one', () => {
  it('flags a material drop, because that is what #333 looked like', () => {
    // 39 where 157 were expected. A drop is either a real deletion or an incomplete listing and
    // discovery cannot tell which — which is exactly why a person has to.
    const p = previousListing(RUN('sharepoint', 39), [PRIOR('sharepoint', 157)])
    expect(p.dropped).toBe(true)
    expect(p.was).toBe(157)
    expect(p.now).toBe(39)
  })

  it('does not flag growth — a bigger estate is not a completeness risk', () => {
    expect(previousListing(RUN('drive', 900), [PRIOR('drive', 500)]).dropped).toBe(false)
  })

  it('does not flag noise', () => {
    // 2% down is an estate, not an incident. Flagging it would train the reader to ignore the box.
    expect(previousListing(RUN('drive', 980), [PRIOR('drive', 1000)]).dropped).toBe(false)
  })

  it('only compares the SAME source', () => {
    // A Drive listing is not evidence about a SharePoint estate.
    expect(previousListing(RUN('sharepoint', 39), [PRIOR('drive', 157)])).toBeNull()
  })

  it('never divides by a previous run that listed nothing', () => {
    // Any number over zero is an infinite increase, which is not a fact worth printing.
    const p = previousListing(RUN('drive', 500), [PRIOR('drive', 0)])
    expect(p.share).toBeNull()
    expect(p.dropped).toBe(false)
  })

  it('returns null when there is nothing to compare', () => {
    expect(previousListing(RUN('drive', 500), [])).toBeNull()
    expect(previousListing(RUN('drive', 500), null)).toBeNull()
    // and never compares a run to itself
    expect(previousListing(RUN('drive', 500), [PRIOR('drive', 900, 'now')])).toBeNull()
  })
})

describe('the panel says nothing when it has nothing to say', () => {
  it('renders nothing without a run', () => {
    expect(text(createElement(DiscoveryCompleteness, { run: null }))).toBe('')
  })

  it('renders nothing for a consistent source with no prior run', () => {
    // The case that matters for restraint. A panel appearing on every run to say "this might be
    // incomplete" is decoration, and it teaches the reader to skip the box that one day carries a
    // real signal.
    expect(text(createElement(DiscoveryCompleteness, { run: RUN('drive', 500), scanList: [] }))).toBe('')
  })

  it('renders nothing for a source it cannot characterise and cannot compare', () => {
    expect(text(createElement(DiscoveryCompleteness, { run: RUN('smb', 500), scanList: [] }))).toBe('')
  })
})

describe('and speaks up when it does', () => {
  it('warns on an index-backed source even with no history', () => {
    const t = text(createElement(DiscoveryCompleteness, { run: RUN('sharepoint', 39), scanList: [] }))
    expect(t).toMatch(/search index/i)
    expect(t).toMatch(/indistinguishable from a genuinely small estate/i)
  })

  it('names both counts on a drop, so the reader can check the claim', () => {
    const t = text(createElement(DiscoveryCompleteness, {
      run: RUN('sharepoint', 39), scanList: [PRIOR('sharepoint', 157)],
    }))
    expect(t).toMatch(/39/)
    expect(t).toMatch(/157/)
    expect(t).toMatch(/75%/)                       // (157-39)/157
    expect(t).toMatch(/cannot tell which/i)        // deletion or incomplete listing — unresolved
  })

  it('states what the comparison can and cannot see', () => {
    // list_scans selects completed_at IS NOT NULL, and an ADR 0020 discover-only run leaves that
    // NULL — so listings that were never assessed are absent from the history. A caveat whose
    // edges a reader cannot see is not a caveat.
    const t = text(createElement(DiscoveryCompleteness, {
      run: RUN('drive', 900), scanList: [PRIOR('drive', 800)],
    }))
    expect(t).toMatch(/completed an assessment/i)
  })

  it('invents no number it does not have', () => {
    // The other half of #333 — comparing against the library's own ItemCount — needs a backend
    // call that does not exist. "39 of ~374" would be made up, and a caveat that is honest about
    // being a caveat beats a fabricated denominator.
    const t = text(createElement(DiscoveryCompleteness, { run: RUN('sharepoint', 39), scanList: [] }))
    expect(t).not.toMatch(/\bof ~/)
    expect(t).not.toMatch(/374/)
  })
})


describe('the caveat sits ABOVE the numbers it qualifies', () => {
  // The flaw this fixes was mine. The panel first sat under the export, reasoning that a reader
  // should meet the caveat before the download button. Wrong reader: the one who matters reads the
  // COUNTS, and a caveat appearing beneath them arrives after they have been believed.
  //
  // Source-level because it asserts ORDER in a tree, which a render of one component cannot see.
  it('Discover renders it before the results, not after', async () => {
    const { readFileSync } = await import('node:fs')
    const { fileURLToPath } = await import('node:url')
    const { dirname, join } = await import('node:path')
    const here = dirname(fileURLToPath(import.meta.url))
    const src = readFileSync(join(here, 'Discover.jsx'), 'utf8')
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      .replace(/^\s*\/\/.*$/gm, '')

    const caveat = src.indexOf('<DiscoveryCompleteness')
    const results = src.indexOf('<DiscoveryResults')
    expect(caveat, 'completeness panel mounted').toBeGreaterThan(-1)
    expect(results, 'results panel mounted').toBeGreaterThan(-1)
    expect(caveat, 'the caveat must precede the counts it qualifies').toBeLessThan(results)
  })
})
