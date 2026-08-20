import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: DiscoverInventoryExport } = await import('./DiscoverInventoryExport.jsx')

const NOW = Date.parse('2026-08-19T12:30:00Z')
const ROWS = [
  { scan_id: 's1', file: 'HR Policy.docx', path: '/HR/HR Policy.docx', parent_folder: '/HR',
    format: 'docx', mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    doc_class: 'document', status: 'assessable', size_kb: 412, owner: 'dana@example.com',
    created_at: '2024-02-01T09:00:00Z', source_modified: '2025-06-11T14:22:00Z',
    discovered_at: '2026-08-19T10:00:00Z', lifecycle_status: 'Active', lifecycle_rule_id: null,
    lifecycle_reason: null, exclusion_reason: null, drive_file_id: 'gd-1', drive_id: null,
    checksum: 'md5-aaa' },
  { scan_id: 's1', file: 'promo.mp4', path: '/Marketing/promo.mp4', parent_folder: '/Marketing',
    format: 'av', mime: 'video/mp4', doc_class: 'media', status: 'unsupported', size_kb: 90210,
    owner: null, created_at: null, source_modified: '2019-01-04T08:00:00Z',
    discovered_at: '2026-08-19T10:04:00Z', lifecycle_status: 'Archive Candidate',
    lifecycle_rule_id: 'legacy-5y', lifecycle_reason: 'not modified in 7.6 yrs',
    exclusion_reason: null, drive_file_id: 'gd-2', drive_id: null, checksum: null },
]

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })

// Records what would have been downloaded, so the assertions are about the BYTES rather than
// about a click having happened.
const recorder = () => {
  const saves = []
  return { saves, save: (blob, filename) => { saves.push({ blob, filename }); return true } }
}
const textOf = (blob) => blob.text()

const render = async (props) => {
  await act(async () => {
    root.render(createElement(DiscoverInventoryExport, {
      scanId: 's1', now: NOW, clock: () => '2026-08-19T12:30:00.000Z', ...props,
    }))
  })
}
const clickButton = async (label) => {
  const btn = [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === label)
  expect(btn, `no "${label}" button`).toBeTruthy()
  await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  return btn
}

describe('DiscoverInventoryExport — when the inventory was taken', () => {
  it('states the instant from the run record, with its age', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS })
    expect(container.textContent).toContain('Inventory taken')
    expect(container.textContent).toContain('3 hours ago')
    expect(container.querySelector('time').getAttribute('datetime'))
      .toBe('2026-08-19T10:00:00.000Z')
  })

  it('derives it from the per-file stamps when the run has none', async () => {
    await render({ run: { id: 's1', status: 'discovered', started_at: '2026-08-19T09:00:00Z' }, rows: ROWS })
    expect(container.textContent).toContain('Inventory taken')
    // The newest of the two rows (10:04), not the run start.
    expect(container.querySelector('time').getAttribute('datetime')).toBe('2026-08-19T10:04:00.000Z')
    expect(container.textContent).toMatch(/derived from the newest per-file discovery stamp/)
  })

  it('says the time is not recorded rather than showing the render clock', async () => {
    await render({ run: { id: 's1', started_at: '2026-08-19T09:00:00Z' },
      rows: ROWS.map((r) => ({ ...r, discovered_at: null })) })
    expect(container.textContent).toContain('Discovery completion time not recorded')
    expect(container.querySelector('time')).toBeNull()
    expect(container.textContent).not.toContain('Inventory taken')
  })

  it('flags a snapshot older than a day', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-01T10:00:00Z' }, rows: ROWS })
    expect(container.textContent).toContain('SNAPSHOT MAY BE STALE')
  })

  it('does not flag a fresh one', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS })
    expect(container.textContent).not.toContain('SNAPSHOT MAY BE STALE')
  })
})

describe('DiscoverInventoryExport — taking the inventory out', () => {
  it('downloads a CSV of every row, named for the run and the instant', async () => {
    const rec = recorder()
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS, save: rec.save })
    await clickButton('Export CSV')
    expect(rec.saves).toHaveLength(1)
    expect(rec.saves[0].filename).toBe('acp-inventory-s1-20260819T100000Z.csv')
    const csv = await textOf(rec.saves[0].blob)
    expect(csv).toContain('HR Policy.docx')
    expect(csv).toContain('promo.mp4')
    expect(csv).toContain('Archive Candidate')
    // Stamped on every row, so the file can still be dated once it leaves ACP.
    expect(csv.split('\r\n').filter(Boolean)).toHaveLength(3)
    expect((csv.match(/2026-08-19T10:00:00\.000Z/g) || []).length).toBe(2)
  })

  it('carries no finding, score or verdict — discovery never opened a file', async () => {
    const rec = recorder()
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS, save: rec.save })
    await clickButton('Export CSV')
    const csv = await textOf(rec.saves[0].blob)
    const head = csv.split('\r\n')[0]
    ;['score', 'issues', 'findings', 'compliant', 'engine', 'pages'].forEach((c) => {
      expect(head.split(',')).not.toContain(c)
    })
    expect(head).toContain('assessability_projected')
  })

  it('downloads a JSON manifest whose missing values are null, not a token', async () => {
    const rec = recorder()
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS, save: rec.save })
    await clickButton('Export JSON')
    const doc = JSON.parse(await textOf(rec.saves[0].blob))
    expect(doc.artifact).toBe('acp-discovery-inventory')
    expect(doc.inventory_taken_at).toBe('2026-08-19T10:00:00.000Z')
    expect(doc.exported_at).toBe('2026-08-19T12:30:00.000Z')
    expect(doc.row_count).toBe(2)
    expect(doc.rows[1].owner).toBeNull()
  })

  it('exports with the instant missing rather than refusing, when nothing was recorded', async () => {
    const rec = recorder()
    await render({ run: { id: 's1' }, rows: ROWS.map((r) => ({ ...r, discovered_at: null })), save: rec.save })
    await clickButton('Export CSV')
    expect(rec.saves[0].filename).toBe('acp-inventory-s1-time-not-recorded.csv')
    const doc = { csv: await textOf(rec.saves[0].blob) }
    expect(doc.csv.split('\r\n')[0]).not.toContain('inventory_taken_at')
  })

  it('names the columns it dropped because every row was empty', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS })
    expect(container.textContent).toMatch(/Not shipped, because every row was empty/)
    expect(container.textContent).toContain('exclusion_reason')
  })

  it('explains the missing token so the reader can act on an empty cell', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS })
    expect(container.textContent).toContain('(not collected)')
  })

  it('confirms what was saved, into a live region that was already there', async () => {
    const rec = recorder()
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS, save: rec.save })
    // Present and empty BEFORE the click — a live region a screen reader has not been observing
    // since before the update is one it may never announce.
    expect(container.querySelector('[role="status"]').textContent).toBe('')
    await clickButton('Export CSV')
    expect(container.querySelector('[role="status"]').textContent).toMatch(/Saved acp-inventory-s1.*2 rows/)
  })

  it('does not claim a download happened when the save reported it did not', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: ROWS,
      save: () => false })
    await clickButton('Export CSV')
    expect(container.querySelector('[role="status"]').textContent).toBe('')
  })
})

describe('DiscoverInventoryExport — an unread inventory is not an empty one', () => {
  it('offers no download and does not claim zero files when the read failed', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: null })
    expect(container.textContent).toContain('could not be read')
    expect(container.textContent).toContain('not an empty estate')
    expect(container.querySelectorAll('button')).toHaveLength(0)
  })

  it('distinguishes a genuinely empty run, which is a real answer', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' }, rows: [] })
    expect(container.textContent).toContain('inventoried no files')
    const btn = [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Export CSV')
    expect(btn.disabled).toBe(true)
  })

  it('reads rows off the inventory envelope when given one', async () => {
    await render({ run: { id: 's1', discovered_at: '2026-08-19T10:00:00Z' },
      inventory: { rows: ROWS, total: 2 } })
    expect(container.textContent).toContain('2 files')
  })
})
