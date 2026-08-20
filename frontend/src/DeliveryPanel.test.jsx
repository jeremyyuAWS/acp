import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// getSettings is the only api.js call this panel makes. `settingsGetter` is swapped per test so a
// pending fetch, a resolved fetch and a rejected fetch can each be driven to their own DOM.
let settingsGetter = () => new Promise(() => {})
vi.mock('./api.js', () => ({ getSettings: () => settingsGetter() }))

const { default: DeliveryPanel } = await import('./DeliveryPanel.jsx')

afterEach(unmountAll)

let container, root
beforeEach(() => {
  settingsGetter = () => new Promise(() => {})
  ;({ container, root } = createTestRoot())
})

const render = async (props) => {
  await act(async () => { root.render(createElement(DeliveryPanel, props)) })
}
const el = (testid) => container.querySelector(`[data-testid="${testid}"]`)
const text = (testid) => el(testid)?.textContent || ''

const FILES = [
  { file: 'policy.docx', drive_file_id: 'gd-1' },
  { file: 'handbook.pdf', drive_file_id: 'gd-2' },
  { file: 'minutes.docx', sp_item_id: 'sp-1' },
]

const ON = { drive_mirror_enabled: true, drive_mirror_folder: 'Remediated' }
const OFF = { drive_mirror_enabled: false, drive_mirror_folder: 'Remediated' }

describe('DeliveryPanel — the mirror setting, pinned in all three states', () => {
  // ON is the SHIPPED DEFAULT (api/store.py:4020 — get_setting(..., "true") != "false"), so this
  // is the configuration most customers are actually in.
  it('ON · names the Drive folder the copy lands in, alongside the original', async () => {
    await render({ files: FILES, settings: ON })
    const claim = text('delivery-destination')
    expect(claim).toContain('ACP storage')
    expect(claim).toContain('“Remediated”')
    expect(claim).toMatch(/2 of them are also written/)
    expect(el('delivery-mirror-unknown')).toBeNull()
  })

  it('OFF · says the mirror is off, and still promises the durable copy', async () => {
    await render({ files: FILES, settings: OFF })
    const claim = text('delivery-destination')
    expect(claim).toContain('ACP storage')
    expect(claim).toMatch(/mirror is switched off/i)
    expect(el('delivery-mirror-unknown')).toBeNull()
  })

  it('UNREAD · renders the absence of the setting, and asserts nothing about Drive', async () => {
    // An explicit null prop is the "not read" state — a caller can render it deliberately, and a
    // failed fetch lands here too.
    await render({ files: FILES, settings: null })
    const claim = text('delivery-destination')
    expect(claim).toContain('ACP storage')
    expect(claim).toMatch(/has not been read/i)
    // Neither verdict, and no folder name pulled from a default nobody read.
    expect(claim).not.toMatch(/switched off/i)
    expect(claim).not.toContain('Remediated')
    // The absence is shown, not swallowed.
    expect(text('delivery-mirror-unknown')).toMatch(/has not been read/i)
  })

  it('UNREAD · a settings object that arrived without the key is still UNREAD, not OFF', async () => {
    await render({ files: FILES, settings: { ai_enabled: true } })
    expect(text('delivery-destination')).toMatch(/has not been read/i)
    expect(text('delivery-destination')).not.toMatch(/switched off/i)
  })

  it('a failed settings fetch renders UNREAD rather than falling back to a default', async () => {
    settingsGetter = () => Promise.reject(new Error('502'))
    await render({ files: FILES })          // no settings prop → the panel fetches
    expect(text('delivery-destination')).toMatch(/has not been read/i)
    expect(text('delivery-destination')).not.toMatch(/switched off/i)
  })

  it('a resolved fetch replaces the unread state with the real configuration', async () => {
    settingsGetter = () => Promise.resolve(ON)
    await render({ files: FILES })
    expect(text('delivery-destination')).toContain('“Remediated”')
    expect(el('delivery-mirror-unknown')).toBeNull()
  })
})

// SCOPED to the element that makes the destination claim. Asserting this over the whole panel
// would sweep in the options list and the unread banner, which are allowed to talk about Drive
// writes — and a test that fails on its own explanatory copy gets weakened rather than heeded.
describe('the banned sentence never reaches the claim element', () => {
  const BANNED = [
    /nothing is written to your drive/i,
    /no files? (?:are|is) written to your drive/i,
    /acp does(?:n't| not) write (?:anything )?to your drive/i,
    /your drive is (?:never )?(?:un)?touched/i,
  ]

  for (const [label, settings] of [['ON', ON], ['OFF', OFF], ['UNREAD', null]]) {
    it(`holds with the mirror ${label}`, async () => {
      await render({ files: FILES, settings })
      const claim = text('delivery-destination')
      expect(claim.length).toBeGreaterThan(0)
      for (const banned of BANNED) expect(claim).not.toMatch(banned)
      // Per-row destinations make the same claim per document; they are in scope for the ban too.
      for (const row of container.querySelectorAll('[data-testid="delivery-row-destination"]')) {
        for (const banned of BANNED) expect(row.textContent).not.toMatch(banned)
      }
    })
  }
})

describe('the copy-not-in-place guarantee', () => {
  it('is rendered identically in every mirror state — it does not move with configuration', async () => {
    const seen = []
    for (const settings of [ON, OFF, null]) {
      const { container: c, root: r } = createTestRoot()
      await act(async () => { r.render(createElement(DeliveryPanel, { files: FILES, settings })) })
      seen.push(c.querySelector('[data-testid="delivery-guarantee"]').textContent)
    }
    expect(new Set(seen).size).toBe(1)
    expect(seen[0]).toMatch(/works on a copy/i)
    expect(seen[0]).toMatch(/not edited in place/i)
  })

  it('is separate from the destination claim, so neither can be read as the other', async () => {
    await render({ files: FILES, settings: ON })
    expect(el('delivery-guarantee')).not.toBeNull()
    expect(el('delivery-destination')).not.toBeNull()
    expect(el('delivery-destination').contains(el('delivery-guarantee'))).toBe(false)
  })
})

describe('per-document delivery', () => {
  it('gives each file its own destination, and a SharePoint file is not promised a Drive copy', async () => {
    await render({ files: FILES, settings: ON })
    const rows = [...container.querySelectorAll('[data-testid="delivery-row"]')]
    expect(rows).toHaveLength(3)
    const byName = (n) => rows.find((r) => r.textContent.includes(n)).textContent
    expect(byName('policy.docx')).toContain('Drive “Remediated”')
    // Read-only SharePoint scopes (sharepointScopes.js:22-24) — no Drive folder, no write-back.
    expect(byName('minutes.docx')).not.toContain('Drive')
    expect(byName('minutes.docx')).toContain('ACP storage')
  })

  it('marks the Drive half as not-known-yet per row while the setting is unread', async () => {
    await render({ files: FILES, settings: null })
    const rows = [...container.querySelectorAll('[data-testid="delivery-row"]')]
    const drive = rows.find((r) => r.textContent.includes('policy.docx')).textContent
    expect(drive).toMatch(/not known yet/i)
    // The SharePoint row is definite even so — it is a fact about the code path, not the setting.
    const sp = rows.find((r) => r.textContent.includes('minutes.docx')).textContent
    expect(sp).not.toMatch(/not known yet/i)
  })

  it('offers a download per file when the host provides one', async () => {
    const onDownload = vi.fn()
    await render({ files: FILES, settings: ON, onDownload })
    const btn = [...container.querySelectorAll('button')].find((b) => b.textContent.includes('Download'))
    await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(onDownload).toHaveBeenCalledWith('policy.docx')
  })

  it('renders no dead download affordance when the host provides none', async () => {
    await render({ files: FILES, settings: ON })
    expect([...container.querySelectorAll('button')].some((b) => b.textContent.includes('Download'))).toBe(false)
  })
})

describe('options', () => {
  it('explains replacement as a separate action, outside the claim element', async () => {
    await render({ files: FILES, settings: ON })
    const opts = text('delivery-options')
    expect(opts).toMatch(/separate action/i)
    expect(opts).toContain('_mova-originals')
    expect(text('delivery-destination')).not.toMatch(/separate action/i)
  })

  it('does not offer a mirror-on suggestion when the setting has not been read', async () => {
    await render({ files: FILES, settings: null })
    expect(text('delivery-options')).not.toMatch(/turn the drive mirror on/i)
  })

  it('suggests turning the mirror on only when it is known to be off', async () => {
    await render({ files: FILES, settings: OFF })
    expect(text('delivery-options')).toMatch(/turn the drive mirror on/i)
  })
})
