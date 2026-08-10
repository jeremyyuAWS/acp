import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { SP_SCOPES, CAN_WRITE_BACK } from './sharepointScopes.js'
import { SpUploadButton } from './SharePoint.jsx'

// This deployment is READ-ONLY against Microsoft 365 (a tenant-admin consent decision, recorded in
// docs/sharepoint-app-registration.md). These pin that posture so it cannot be widened by accident:
// re-adding a *.ReadWrite scope is a real permission change and should have to update this test on
// purpose, not slip in unnoticed.

describe('SharePoint scopes are read-only and reach SharePoint, not just OneDrive', () => {
  it('requests no write scope', () => {
    const write = SP_SCOPES.filter((s) => /\.ReadWrite/i.test(s))
    expect(write, `unexpected write scope(s): ${write.join(', ')}`).toEqual([])
    expect(CAN_WRITE_BACK).toBe(false)
  })

  it('requests the org-scoped reads the site picker and file download need', () => {
    // Sites.Read.All is what GET /sharepoint/sites (Graph /sites?search=*) needs; Files.Read.All
    // reaches team-site libraries and shared files, where plain Files.Read is OneDrive alone.
    expect(SP_SCOPES).toContain('Sites.Read.All')
    expect(SP_SCOPES).toContain('Files.Read.All')
    expect(SP_SCOPES).toContain('User.Read')
    // Not the OneDrive-only read, which cannot list SharePoint sites.
    expect(SP_SCOPES).not.toContain('Files.Read')
  })
})

describe('the write-back button honours the read-only scopes', () => {
  it('renders nothing when no write scope is requested', () => {
    // A button that can only 403 should not be shown. Gated on CAN_WRITE_BACK, so it reappears on
    // its own if a write scope is ever added back.
    const html = renderToStaticMarkup(
      <SpUploadButton itemId="i" driveId="d" blob={new Blob(['x'])} score={90} engine="docx" file="f.docx" />,
    )
    expect(html).toBe('')
  })
})
