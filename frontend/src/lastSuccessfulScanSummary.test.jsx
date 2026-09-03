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
const FILES = [
  { id: '1', name: 'one.docx', file_type: 'docx', can_assess: true },
  { id: '2', name: 'two.pdf', file_type: 'pdf', can_assess: true, unreadable: true },
]

describe('LastSuccessfulScanSummary', () => {
  it('shows the recorded source, folders, criteria, lifecycle outcomes and enumeration evidence', async () => {
    const container = await render({
      run: { id: 'scan-123', status: 'discovered', source: 'drive' },
      runAt: RUN_AT,
      files: FILES,
      inventory: { discovered: 2, assessment_eligible: 2 },
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
    expect(text).toContain('Discovered2')
    expect(text).toContain('Eligible')
    expect(container.querySelector('[role="group"][aria-label="Discovered: 2"]')).toBeTruthy()
    expect(text).toContain('Last scan details')
    const details = container.querySelector('details')
    expect(details.open).toBe(false)
    expect(details.textContent).toContain('Scan IDscan-123')
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
      files: FILES,
      scope: { kind: 'sharepoint', scan_scope: null, lifecycle_rules_enabled: 0,
               enumeration: { complete: false, files_found: 10 } },
    })
    expect(unrestricted.textContent).toContain('Whole OneDrive')
    expect(unrestricted.textContent).toContain('All criteria')
    expect(unrestricted.textContent).toContain('No enabled rules')
    expect(unrestricted.textContent).toContain('Not verified')

    const historical = await render({
      run: { id: 'scan-old', status: 'discovered', source: 'drive' }, scope: { kind: 'drive' }, files: FILES,
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
      files: FILES,
      scope: { kind: 'drive', scan_scope: null, lifecycle_rules_enabled: 0 },
    })
    expect(container.textContent).toContain('Last successful scan')
    expect(container.textContent).toContain('Whole Drive')
  })

  it('uses the whole listing total rather than a later assessed-row subset', async () => {
    const container = await render({
      run: { id: 'scan-wide', status: 'discovered', source: 'drive' },
      files: FILES,
      inventory: { discovered: 6916, assessment_eligible: 986 },
      scope: { kind: 'drive' },
    })
    expect(container.textContent).toContain('Discovered6,916')
    expect(container.textContent).toContain('Eligible986')
    expect(container.textContent).not.toContain('Discovered2')
  })

  it('shows an unknown eligible count as unknown rather than zero', async () => {
    const container = await render({
      run: { id: 'scan-old', status: 'discovered', source: 'drive' },
      files: FILES,
      inventory: { discovered: 2 },
      scope: { kind: 'drive' },
    })
    expect(container.textContent).toContain('Eligible—')
    expect(container.textContent).toContain('Assessable count was not recorded')
  })
})
