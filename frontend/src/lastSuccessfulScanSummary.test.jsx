import { afterEach, describe, expect, it } from 'vitest'
import { act } from 'react-dom/test-utils'
import LastSuccessfulScanSummary from './LastSuccessfulScanSummary.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(() => unmountAll())

async function render(props) {
  const { container, root } = createTestRoot()
  await act(async () => root.render(<LastSuccessfulScanSummary {...props} />))
  return container
}

const RUN_AT = { recorded: true, absolute: 'Sep 2, 2026, 8:04 AM PDT', relative: '6 hours ago' }

describe('LastSuccessfulScanSummary', () => {
  it('shows the recorded source, folders, criteria, lifecycle outcomes and enumeration evidence', async () => {
    const container = await render({
      run: { id: 'scan-123', status: 'discovered', source: 'drive' },
      runAt: RUN_AT,
      scope: {
        kind: 'folder', folder_name: 'UTSW DEMO V3', folders_walked: 7,
        folders: [{ id: 'f1', name: 'UTSW DEMO V3' }],
        scan_scope: { '1.1.1': ['docx', 'pdf'], '1.3.1': ['docx'], '1.4.3': ['pptx'] },
        lifecycle_rules_enabled: 2, lifecycle_archive: 5, lifecycle_delete: 1,
        lifecycle_tagged: 3,
        enumeration: { complete: true, files_found: 986 },
      },
    })
    const text = container.textContent
    expect(text).toContain('Last successful scan')
    expect(text).toContain('Scan ID scan-123')
    expect(text).toContain('Google Drive')
    expect(text).toContain('UTSW DEMO V3')
    expect(text).toContain('7 folders traversed')
    expect(text).toContain('3 criteria')
    expect(text).toContain('DOCX, PDF, PPTX')
    expect(text).toContain('2 enabled')
    expect(text).toContain('5 archive · 1 deletion · 3 tagged')
    expect(text).toContain('Complete')
    expect(text).toContain('986 files found at the source')
  })

  it('distinguishes unrestricted and unrecorded historical scan settings', async () => {
    const unrestricted = await render({
      run: { id: 'scan-1', status: 'discovered', source: 'sharepoint' },
      scope: { kind: 'sharepoint', scan_scope: null, lifecycle_rules_enabled: 0,
               enumeration: { complete: false, files_found: 10 } },
    })
    expect(unrestricted.textContent).toContain('Whole OneDrive')
    expect(unrestricted.textContent).toContain('All criteria')
    expect(unrestricted.textContent).toContain('No enabled rules')
    expect(unrestricted.textContent).toContain('Not verified')

    const historical = await render({
      run: { id: 'scan-old', status: 'discovered', source: 'drive' }, scope: { kind: 'drive' },
    })
    expect(historical.textContent).toContain('Criteria were not preserved on this historical run.')
    expect(historical.textContent).toContain('Lifecycle execution details are unavailable.')
  })

  it('does not label a non-terminal run as the last successful scan', async () => {
    const container = await render({ run: { id: 'scan-running', status: 'running', source: 'drive' } })
    expect(container.textContent).toBe('')
  })

  it('stays visible after the successful run advances into assessment', async () => {
    const container = await render({
      run: { id: 'scan-assessed', status: 'done', source: 'drive', discovered_at: '2026-09-02T15:04:00Z' },
      runAt: RUN_AT,
      scope: { kind: 'drive', scan_scope: null, lifecycle_rules_enabled: 0 },
    })
    expect(container.textContent).toContain('Last successful scan')
    expect(container.textContent).toContain('Whole Drive')
  })
})
