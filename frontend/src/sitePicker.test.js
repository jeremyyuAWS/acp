import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The clients shipped in the same change; this is what calls them. Without a picker,
// listSharePointSites had no caller and a SharePoint scan had no way to name a site — so the
// route, the client and the scan path were each complete and the feature still did not exist.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('SitePicker', () => {
  it('exists and uses both list clients', () => {
    expect(existsSync(join(HERE, 'SitePicker.jsx'))).toBe(true)
    const s = read('SitePicker.jsx')
    expect(s).toContain("import { listSharePointSites, listSharePointDrives, getConfig } from './api.js'")
  })

  it('surfaces the route error verbatim', () => {
    // The route distinguishes a missing SCOPE (403 → names Sites.Read.All and admin consent)
    // from a transport failure. Flattening that to "could not load sites" would send an
    // operator looking in the wrong place for the commonest failure this feature has.
    const s = read('SitePicker.jsx')
    expect(s).toMatch(/setErr\(e\?\.message/)
    expect(s).toMatch(/\{err\}/)
  })

  it('shows a site with no libraries as such, before the scan', () => {
    // A site with four libraries and one with none look identical from the name alone, and the
    // second is the case where a scan returns nothing and the operator cannot tell whether that
    // is the site or the product.
    const s = read('SitePicker.jsx')
    expect(s).toMatch(/scanning this site would return nothing/i)
  })

  it('does not re-fetch libraries on every expand toggle', () => {
    const s = read('SitePicker.jsx')
    expect(s).toMatch(/if \(drives\[site\.id\]\) return/)
  })

  it('selects SEVERAL sites and hands back an array', () => {
    // An estate assessment covers a department, not a team site. One site at a time was the
    // honest UI over a backend that walked the first site of a multi-site request and dropped
    // the rest silently — so the picker growing checkboxes is half the fix, not a convenience.
    //
    // Always an array, including for one site: a caller that branches on the shape of its
    // argument gets the single case right and the multi case wrong, which is the direction that
    // under-reports an estate.
    const s = read('SitePicker.jsx')
    expect(s).toMatch(/type="checkbox"/)
    expect(s).toMatch(/onScan\(picked\)/)
    expect(s).toMatch(/setPicked\(/)
  })

  it('keeps the selection when the filter changes', () => {
    // Building a thirty-site scan means searching "finance", ticking two, searching "hr",
    // ticking two more. Clearing on a keystroke would make that impossible and would read as
    // the picker losing the operator's work.
    const s = read('SitePicker.jsx')
    const q = s.slice(s.indexOf('useEffect'), s.indexOf('const expand'))
    expect(q).not.toMatch(/setPicked\(\[\]\)/)
  })

  it('reads the site cap from /config rather than hardcoding it', () => {
    // The server enforces it (routes/scans.sharepoint_site_overflow) and the walk caps itself.
    // A number held here would disagree with the deployment the moment ACP_SP_MAX_SITES moved:
    // the picker would block a selection the server accepts, or wave one through that it will
    // refuse after the operator has finished choosing.
    const s = read('SitePicker.jsx')
    expect(s).toMatch(/sharepoint_max_sites/)
  })
})

describe('Discover wires it', () => {
  it('renders the picker and passes ONE site id as `folder`', () => {
    // _list treats `folder` as the site for source='sharepoint' (#156), so this is one
    // parameter reused rather than a second one threaded through five call sites. The single
    // case keeps that shape deliberately: every saved link and queued job names one site the
    // way it always did.
    const d = read('Discover.jsx')
    expect(d).toContain("import SitePicker from './SitePicker.jsx'")
    expect(d).toMatch(/onScan\('sharepoint', ids\[0\] \|\| null\)/)
  })

  it('passes SEVERAL site ids as `folders`, the multi-root form', () => {
    // scanner._sp_locations splits the same `folders` list into folder pairs and bare site ids,
    // so a multi-site selection needs no third parameter — and App carries it through the scope
    // review modal, which has no folder tree that could hold it.
    const d = read('Discover.jsx')
    expect(d).toMatch(/onScan\('sharepoint', null, \{ folders: ids \}\)/)
    const a = read('App.jsx')
    expect(a).toMatch(/folders = null \} = \{\}\) =>/)
    expect(a).toMatch(/folders: preset/)
  })

  it('gates the button on the SharePoint token', () => {
    // Same gate the Drive button uses. Offering a picker that cannot authenticate produces an
    // error where a missing button would have produced an obvious next step: connect the source.
    const d = read('Discover.jsx')
    expect(d).toMatch(/\{hasSPToken && \(/)
    expect(d).toMatch(/hasSPToken = false/)
  })

  it('is fed the token flag by App', () => {
    // The prop existing and never being passed is the failure this catches: the button would
    // simply never render, with nothing anywhere reporting why.
    expect(read('App.jsx')).toMatch(/hasSPToken=\{hasSPToken\}/)
  })

  it('keeps the SharePoint site picker independent of the Drive scan gate', () => {
    // The 2026-09-02 PRD simplification removed Discover's Drive scan button entirely — users
    // initiate scans from the Sources tab. The SharePoint site picker remains as Discover's own
    // local modal because it is a selection step (which site to scan), not a repeat rescan action.
    const d = read('Discover.jsx')
    expect(d).toMatch(/const \[showSites, setShowSites\] = useState\(false\)/)
    expect(d).not.toMatch(/showPicker/)
    expect(d).not.toMatch(/onScan\('drive', null, \{ folderFirst: true \}\)/)
    expect(d).toMatch(/onScan\('sharepoint', ids\[0\] \|\| null\)/)
  })
})
