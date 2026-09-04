import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SourceVisibility from './SourceVisibility.jsx'

const sharePointScope = {
  kind: 'sharepoint',
  sites: [
    { id: 's1', name: 'Clinical', status: 'complete', libraries: [{ id: 'l1', name: 'Documents' }] },
    { id: 's2', name: 'Research', status: 'complete', libraries: [
      { id: 'l2', name: 'Studies' }, { id: 'l3', name: 'Published' },
    ] },
  ],
}

describe('SourceVisibility', () => {
  it('names the selected SharePoint sites and document-library count', () => {
    const html = renderToStaticMarkup(<SourceVisibility source="sharepoint" scope={sharePointScope} />)
    expect(html).toContain('Content source')
    expect(html).toContain('SharePoint')
    expect(html).toContain('Clinical')
    expect(html).toContain('Research')
    expect(html).toContain('3 document libraries')
    expect(html).toContain('<details')
    expect(html).toContain('Documents')
    expect(html).toContain('Studies')
    expect(html).toContain('Published')
  })

  it('distinguishes OneDrive from SharePoint and preserves Google Drive visibility', () => {
    expect(renderToStaticMarkup(<SourceVisibility source="sharepoint" scope={{ kind: 'sharepoint' }} />))
      .toContain('OneDrive')
    expect(renderToStaticMarkup(<SourceVisibility source="drive" scope={{ kind: 'drive' }} />))
      .toContain('Google Drive')
  })
})
