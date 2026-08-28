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
    expect(s).toContain("import { listSharePointSites, listSharePointDrives } from './api.js'")
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
})

describe('Discover wires it', () => {
  it('renders the picker and passes the site id as `folder`', () => {
    // _list treats `folder` as the site for source='sharepoint' (#156), so this is one
    // parameter reused rather than a second one threaded through five call sites.
    const d = read('Discover.jsx')
    expect(d).toContain("import SitePicker from './SitePicker.jsx'")
    expect(d).toMatch(/onScan\('sharepoint', siteId\)/)
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
    // The SharePoint site picker is still Discover's own local modal; Drive folder selection no
    // longer has a matching local state at all — it opens the SAME app-level scan gate every
    // other entry point does (2026-08-28: a standalone FolderPicker modal used to duplicate that
    // gate's own folder step, so picking a folder there immediately re-asked the same question a
    // second time). One shared flag between the two would open both or neither; there is no
    // longer a flag to share.
    const d = read('Discover.jsx')
    expect(d).toMatch(/const \[showSites, setShowSites\] = useState\(false\)/)
    expect(d).not.toMatch(/showPicker/)
    expect(d).toMatch(/onScan\('drive', null, \{ folderFirst: true \}\)/)
    expect(d).toMatch(/onScan\('sharepoint', siteId\)/)
  })
})
