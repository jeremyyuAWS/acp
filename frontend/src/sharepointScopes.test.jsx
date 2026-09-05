import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SP_SCOPES, CAN_PUBLISH_COPY, CAN_WRITE_BACK } from './sharepointScopes.js'
import { SpUploadButton } from './SharePoint.jsx'

// Release is an explicit write of a corrected COPY. These pin the delegated scopes that make that
// promise executable without granting application/background access.

describe('SharePoint scopes can publish corrected copies', () => {
  it('requests delegated write scopes for files and team sites', () => {
    const write = SP_SCOPES.filter((s) => /\.ReadWrite/i.test(s))
    expect(write).toEqual(['Files.ReadWrite.All', 'Sites.ReadWrite.All'])
    expect(CAN_PUBLISH_COPY).toBe(true)
    expect(CAN_WRITE_BACK).toBe(false)
  })

  it('requests the org-scoped reads the site picker and file download need', () => {
    // Sites.Read.All is what GET /sharepoint/sites (Graph /sites?search=*) needs; Files.Read.All
    // reaches team-site libraries and shared files, where plain Files.Read is OneDrive alone.
    expect(SP_SCOPES).toContain('Sites.ReadWrite.All')
    expect(SP_SCOPES).toContain('Files.ReadWrite.All')
    expect(SP_SCOPES).toContain('User.Read')
    // Not the OneDrive-only read, which cannot list SharePoint sites.
    expect(SP_SCOPES).not.toContain('Files.Read')
  })
})

describe('source replacement remains disabled', () => {
  it('does not turn the legacy overwrite button on merely because Release can create copies', () => {
    const html = renderToStaticMarkup(
      <SpUploadButton itemId="i" driveId="d" blob={new Blob(['x'])} score={90} engine="docx" file="f.docx" />,
    )
    expect(html).toBe('')
  })
})
