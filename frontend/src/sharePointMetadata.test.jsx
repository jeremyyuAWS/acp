// The panel that shows SharePoint's own vocabulary for a document — and, per field, whether ACP
// actually read it.
//
// Every field here can be empty for two opposite reasons, and a panel that renders both as "—"
// actively misleads: an operator who reads "Sensitivity label: —" and concludes their estate is
// unlabelled, when nobody ever asked Graph for the labels, has been told something false by this
// screen. One is an answer about their tenant; the other is a task for ACP.
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: SharePointMetadata } = await import('./SharePointMetadata.jsx')

const HERE = dirname(fileURLToPath(import.meta.url))

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(SharePointMetadata, props)) })
  return container
}
afterEach(() => unmountAll())

const f = (value, state = 'present', reason = null) => ({ value, state, reason })

describe('SharePointMetadata', () => {
  it('renders nothing for a document with no SharePoint record', async () => {
    // Google Drive, a local corpus, every scan recorded before this shipped. A panel full of
    // "not recorded" rows on a Drive file is noise that trains the reader to skip the panel on
    // the files where it matters.
    expect((await mount({})).textContent).toBe('')
    expect((await mount({ metadata: { fields: {} } })).textContent).toBe('')
  })

  it('shows the tenant’s own vocabulary', async () => {
    const c = await mount({ metadata: { fields: {
      site_name: f('Regulatory'), library_name: f('Policies'),
      content_type: f('Superseded Policy'), retention_label: f('Retain 7 Years'),
      managed_columns: f({ 'Records Category': 'Superseded' }),
    } } })
    expect(c.textContent).toMatch(/Content type/)
    expect(c.textContent).toMatch(/Superseded Policy/)
    expect(c.textContent).toMatch(/Retain 7 Years/)
    expect(c.textContent).toMatch(/Records Category: Superseded/)
  })

  it('says NOT READ, not a dash, when ACP could not read a field', async () => {
    // THE case. A dash is what an unset field would look like too, and the two call for
    // opposite responses.
    const c = await mount({ metadata: { fields: {
      sensitivity_label: f(null, 'unavailable', 'Graph exposes this on beta only'),
    } } })
    expect(c.textContent).toMatch(/Not read/)
    expect(c.textContent).toMatch(/beta only/)
    expect(c.textContent).not.toMatch(/SharePoint records none/)
  })

  it('says SharePoint RECORDS NONE when the tenant genuinely sets nothing', async () => {
    // The other direction, and what makes the first meaningful: this is an answer the operator
    // can act on by changing their SharePoint, not by changing ACP.
    const c = await mount({ metadata: { fields: {
      retention_label: f(null, 'not_configured'),
    } } })
    expect(c.textContent).toMatch(/SharePoint records none/)
    expect(c.textContent).not.toMatch(/Not read/)
  })

  it('warns once at the top when any field went unread', async () => {
    // A reader scanning for a value needs to know before they start that some of these blanks
    // are ACP's and not their tenant's.
    const c = await mount({ metadata: { fields: {
      content_type: f('Policy'),
      retention_label: f(null, 'unavailable', 'the listItem expansion was refused'),
      sensitivity_label: f(null, 'unavailable', 'beta only'),
    } } })
    expect(c.textContent).toMatch(/2 fields below could not be read from\s+SharePoint/)
    expect(c.textContent).toMatch(/not the same as SharePoint recording nothing/)
  })

  it('says nothing about fields that cannot exist for this item', async () => {
    // A OneDrive file has no site. A row saying so on every OneDrive document is a permanent
    // reminder of a non-problem, which is how a panel earns being ignored.
    const c = await mount({ metadata: { fields: {
      site_name: f(null, 'not_applicable'),
      content_type: f('Document'),
    } } })
    expect(c.textContent).not.toMatch(/Site/)
    expect(c.textContent).toMatch(/Document/)
  })

  it('leads with the two rows the panel exists for', async () => {
    // Not alphabetical: "Content type" and "Retention label" must not end up buried between
    // "Checked out by" and "Created by".
    const c = await mount({ metadata: { fields: {
      created_by: f('Alice'), checked_out_by: f('Bob'),
      content_type: f('Policy'), retention_label: f('Retain 7 Years'),
      site_name: f('Regulatory'),
    } } })
    const t = c.textContent
    expect(t.indexOf('Content type')).toBeLessThan(t.indexOf('Created by'))
    expect(t.indexOf('Retention label')).toBeLessThan(t.indexOf('Checked out by'))
  })

  it('renders a declared-record flag as words, not as true/false', async () => {
    const c = await mount({ metadata: { fields: { is_record: f(true) } } })
    expect(c.textContent).toMatch(/Declared a record/)
    expect(c.textContent).toMatch(/Yes/)
  })
})

describe('FileDrawer mounts it', () => {
  it('renders the panel from the file’s own metadata record, at both drawer layouts', () => {
    const d = readFileSync(join(HERE, 'FileDrawer.jsx'), 'utf8')
    expect(d).toContain("import SharePointMetadata from './SharePointMetadata.jsx'")
    expect(d).toMatch(/const spBlock = <SharePointMetadata metadata=\{file\.sp_metadata\} \/>/)
    // Both layouts, because a drawer that shows it in one and not the other is a field that
    // exists or not depending on which screen opened it.
    expect((d.match(/\{spBlock\}/g) || []).length).toBe(2)
  })
})
