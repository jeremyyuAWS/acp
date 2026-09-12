import { afterEach, expect, it, vi } from 'vitest'
import { act, createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationLiveDocuments from './RemediationLiveDocuments.jsx'
import { getFileRemediationDiffs, getScanRemediationDiffs, getFindingDispositions, listHitlQueue, getReleaseStatus, getSourceStatus } from './api.js'
vi.mock('./api.js', () => ({ getFileRemediationDiffs: vi.fn(), getScanRemediationDiffs: vi.fn(), getFindingDispositions: vi.fn(), listHitlQueue: vi.fn(), getReleaseStatus: vi.fn(), getSourceStatus: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(async () => { await unmountAll(); vi.clearAllMocks(); getReleaseStatus.mockReset(); getSourceStatus.mockReset(); vi.useRealTimers() })
const files = ['A.docx', 'B.docx'].map(file => ({ file, name: file, status: 'analysed', issues: [{ wcag: 'SC_1_1_1', severity: 'SERIOUS' }] }))
const fix = { file: 'A.docx', rule_id: 'SC_1_1_1', before: 'Missing alt text', after: 'A mountain lake', page: 2 }
const props = { scanId: 'run', files, cap: { docx: { '1.1.1': 'assisted' } }, assessment: { docx: { '1.1.1': 'auto' } }, fixes: [fix], fixTotal: 9 }
async function mount(extra = {}) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(RemediationLiveDocuments, { ...props, ...extra })))
  return { root, container }
}
it('reuses Documents, keeps all files visible, and opens evidence grouped by SC for only the selected file', async () => {
  getFileRemediationDiffs.mockResolvedValue([fix, { ...fix, rule_id: 'SC_3_1_1', before: '', after: 'en-US' }])
  const { container } = await mount()
  expect(container.textContent).toContain('Documents')
  expect(container.querySelector('.col-category [aria-label="Applied — verification pending: 1 records"]')).not.toBeNull()
  expect(container.querySelector('.col-category details')).toBeNull()
  expect(container.textContent).toContain('9 across the run')
  expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
  await act(async () => [...container.querySelectorAll('button')].find(n => n.textContent.includes('View fixes')).click())
  expect(getFileRemediationDiffs).toHaveBeenCalledWith('run', 'A.docx')
  const dialog = container.querySelector('.remediation-file-page')
  expect(dialog.querySelector('h2').textContent).toBe('A.docx')
  expect(dialog.querySelectorAll('.remediation-sc-card')).toHaveLength(2)
  expect(dialog.textContent).toContain('SC 1.1.1 Non-text Content')
  expect(dialog.textContent).toContain('A mountain lake')
  expect(dialog.textContent).toContain('Page 2')
  expect(dialog.textContent).toContain('Verification: Not reported')
})
it('refreshes an open file as completed work arrives and preserves loaded evidence when the read fails', async () => {
  getFileRemediationDiffs.mockResolvedValue([fix])
  const { root, container } = await mount()
  await act(async () => [...container.querySelectorAll('button')].find(n => n.textContent.includes('View fixes')).click())
  getFileRemediationDiffs.mockRejectedValue(new Error('offline'))
  await act(async () => root.render(createElement(RemediationLiveDocuments, { ...props, refreshKey: 'next' })))
  expect(container.querySelector('.remediation-file-page').textContent).toContain('does not establish that the file has no fixes')
  expect(container.querySelector('.remediation-file-page').textContent).toContain('A mountain lake')
  expect(getFileRemediationDiffs).toHaveBeenCalledTimes(2)
})

it('ignores a late response after a different document is opened', async () => {
  let finishFirst
  getFileRemediationDiffs.mockImplementation((_id, file) => file === 'A.docx'
    ? new Promise(resolve => { finishFirst = resolve })
    : Promise.resolve([{ ...fix, file: 'B.docx', after: 'Second document' }]))
  const { container } = await mount()
  const buttons = () => [...container.querySelectorAll('button')].filter(n => n.textContent.includes('View fixes'))
  await act(async () => buttons()[0].click())
  await act(async () => [...container.querySelectorAll('button')].find(n => n.textContent === '← All documents').click())
  await act(async () => buttons()[1].click())
  await act(async () => finishFirst([fix]))
  const drawer = container.querySelector('.remediation-file-page')
  expect(drawer.textContent).toContain('Second document')
  expect(drawer.textContent).not.toContain('A mountain lake')
})

it('offers remediation-state filtering while keeping change records separate from findings', async () => {
  const { container } = await mount({ fixes: [{ ...fix, verified: true }] })
  const button = [...container.querySelectorAll('button')].find(node => node.querySelector('[title="Fixed and verified"]'))
  expect(button.textContent).toContain('Verified 0 · 1 change records')
  await act(async () => button.click())
  expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
  expect(container.querySelector('tbody').textContent).toContain('A.docx')
  expect(container.querySelector('tbody').textContent).not.toContain('B.docx')
})

it('uses an Assess-style file page with remediation pills and returns focus to View fixes', async () => {
  getFileRemediationDiffs.mockResolvedValue([fix])
  const { container } = await mount()
  const open = [...container.querySelectorAll('button')].find(n => n.textContent.includes('View fixes'))
  open.focus()
  await act(async () => open.click())
  const page = container.querySelector('.remediation-file-page')
  expect(document.activeElement).toBe(page.querySelector('h2'))
  expect(page.querySelector('.remediation-file-summary')).not.toBeNull()
  expect(page.querySelector('.remediation-sc-card .remediation-category-pill')).not.toBeNull()
  expect(page.querySelectorAll('details')).toHaveLength(1)
  expect(page.querySelector('details').open).toBe(false)
  expect(page.querySelector('details summary').textContent).toBe('Category legend')
  expect(container.querySelector('[role=dialog]')).toBeNull()
  await act(async () => [...page.querySelectorAll('button')].find(n => n.textContent === '← All documents').click())
  expect(document.activeElement).toBe(open)
})

it('moves only confirmed finding categories and keeps totals', async () => {
  vi.useFakeTimers()
  const ledger = { available:true, batch_id:'batch', items: files.map((f,i) => ({finding_id:`f${i}`,file:f.file,rule_id:'1.1.1',disposition:'awaiting_review',review_item_id:`q${i}`})) }
  getFindingDispositions.mockResolvedValue(ledger)
  listHitlQueue.mockResolvedValue([])
  getScanRemediationDiffs.mockResolvedValue({items:[],total:0,documents:0,loaded:0,complete:true})
  const snapshot={batch_id:'batch',state:'processing',documents:{processing:2}}
  const {root,container}=await mount({snapshot,connected:true})
  await act(async()=>vi.advanceTimersByTime(400))
  expect(container.querySelectorAll('.live-document-table tbody tr')).toHaveLength(2)
  expect(container.querySelector('.live-document-table').parentElement.className).toBe('document-findings-scroll')
  expect(container.querySelectorAll('.live-document-table .findings-criteria-heading br')).toHaveLength(1)
  expect(container.querySelectorAll('.live-document-table .findings-total-heading br')).toHaveLength(1)
  expect(container.querySelector('.live-document-categories').textContent).toContain('Remaining 2')
  expect(container.querySelector('.live-document-changed')).toBeNull()
  getFindingDispositions.mockResolvedValue({...ledger,items:ledger.items.map((r,i)=>i? r:{...r,disposition:'approved_pending_verification'})})
  listHitlQueue.mockResolvedValue([{id:'q0',file:'A.docx',applied:true,proposals:[{model:'real',model_call_id:'call'}]}])
  await act(async()=>root.render(createElement(RemediationLiveDocuments,{...props,snapshot,connected:true,events:[{id:1,scan_id:'run',kind:'remediate.fix_applied'}]})))
  await act(async()=>vi.advanceTimersByTime(400))
  expect(container.querySelector('.live-document-categories').textContent).toContain('AI applied 1')
  expect(container.querySelector('.live-document-changed')).not.toBeNull()
  expect(container.textContent).toContain('Finding categories updated for 1 document.')
  expect(getFindingDispositions).toHaveBeenCalledTimes(2)
  await act(async()=>root.render(createElement(RemediationLiveDocuments,{...props,snapshot,connected:true,events:[{id:1,scan_id:'run',kind:'remediate.fix_applied'},{id:2,scan_id:'other',kind:'remediate.fix_applied'}]})))
  await act(async()=>vi.advanceTimersByTime(400))
  expect(getFindingDispositions).toHaveBeenCalledTimes(2)
})

it('does not invent category movement when canonical findings are incomplete', async () => {
  vi.useFakeTimers()
  getFindingDispositions.mockResolvedValue({available:true,batch_id:'batch',items:[]})
  listHitlQueue.mockResolvedValue([])
  getScanRemediationDiffs.mockResolvedValue({items:[{...fix,verified:true}],total:1,documents:1,loaded:1,complete:true})
  const {container}=await mount({snapshot:{batch_id:'batch'},connected:true})
  await act(async()=>vi.advanceTimersByTime(400))
  expect(container.querySelector('.live-document-table')).toBeNull()
  expect(container.textContent).toContain('outcomes are reconciling')
  expect(container.textContent).toContain('AI 2')
})

it('distinguishes unique WCAG criteria from individual findings without multiplying', async () => {
  const repeated=[{file:'Many.docx',status:'analysed',issues:[
    {wcag:'SC_1_1_1',severity:'SERIOUS'},{wcag:'SC_1_1_1',severity:'SERIOUS'},
    {wcag:'SC_1_3_1',severity:'SERIOUS'},
  ]}]
  const {container}=await mount({files:repeated})
  expect(container.textContent).toContain('WCAG criteria with issues')
  expect(container.textContent).toContain('Total findings')
  expect(container.querySelector('.col-criteria').textContent).toBe('2')
  expect(container.querySelector('.col-findings').textContent).toBe('3')
  const table = container.querySelector('.document-findings-table')
  expect(table.parentElement.getAttribute('tabindex')).toBe('0')
  expect(table.parentElement.getAttribute('aria-label')).toBe('Document findings table')
  expect(table.querySelector('.findings-criteria-heading br')).not.toBeNull()
  expect(table.querySelector('.findings-total-heading br')).not.toBeNull()
  expect(table.querySelector('.findings-criteria-heading').nextElementSibling).toBe(table.querySelector('.findings-total-heading'))
})

it('filters documents with the shared recorded progress counts without conflating verification and release', async () => {
  vi.useFakeTimers()
  getFindingDispositions.mockResolvedValue({available:true,batch_id:'batch',items:files.map((f,i)=>({finding_id:`f${i}`,file:f.file,rule_id:'1.1.1',disposition:i ? 'awaiting_review' : 'resolved_verified'}))})
  listHitlQueue.mockResolvedValue([])
  getScanRemediationDiffs.mockResolvedValue({items:[],total:0})
  const {container}=await mount({snapshot:{batch_id:'batch'},connected:true})
  await act(async()=>vi.advanceTimersByTime(400))
  expect(container.querySelector('.progress-verified strong').textContent).toBe('1')
  expect(container.querySelector('.progress-ready strong').textContent).toBe('0')
  await act(async()=>container.querySelector('.progress-verified').click())
  expect(container.querySelectorAll('.live-document-table tbody tr')).toHaveLength(1)
  expect(container.querySelector('.live-document-table tbody th').textContent).toBe(files[0].file)
  await act(async()=>container.querySelector('.remediation-progress-summary-heading button').click())
  expect(container.querySelectorAll('.live-document-table tbody tr')).toHaveLength(2)
})

it('filters assessment fallback by supplied progress and clears filters when assessment changes', async () => {
  const progressDocuments=[{file:'A.docx',progressState:'ready'},{file:'B.docx',progressState:'attention'}]
  const {root,container}=await mount({progressDocuments})
  await act(async()=>container.querySelector('.progress-ready').click())
  expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
  expect(container.querySelector('tbody').textContent).toContain('A.docx')
  expect(container.querySelector('tbody').textContent).not.toContain('B.docx')
  await act(async()=>root.render(createElement(RemediationLiveDocuments,{...props,scanId:'new',progressDocuments})))
  expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
})

it('overlays recorded Release readiness and current delivery receipt onto live findings',async()=>{
  vi.useFakeTimers()
  const corrected=files.map(file=>({...file,compliant:true,remediated_at:'2026-09-11T12:00:00Z',corrected_sha256:'current'}))
  getFindingDispositions.mockResolvedValue({available:true,batch_id:'batch',items:files.map((file,i)=>({finding_id:`f${i}`,file:file.file,rule_id:'1.1.1',disposition:'resolved_verified'}))})
  listHitlQueue.mockResolvedValue([])
  getScanRemediationDiffs.mockResolvedValue({items:[],total:0})
  getSourceStatus.mockResolvedValue({files:[]})
  getReleaseStatus.mockResolvedValue({documents:[{file:'A.docx',status:'published',artifact_digest:'sha256:current'}]})
  const {container}=await mount({files:corrected,snapshot:{batch_id:'batch'},connected:true})
  await act(async()=>vi.advanceTimersByTime(400))
  expect(container.querySelector('.progress-published strong').textContent).toBe('1')
  expect(container.querySelector('.progress-ready strong').textContent).toBe('1')
  expect(container.querySelector('.progress-processing strong').textContent).toBe('0')
})

it('reuses source freshness for thirty seconds while refreshing new release receipts',async()=>{
  vi.useFakeTimers()
  getFindingDispositions.mockResolvedValue({available:true,batch_id:'batch',items:files.map((file,i)=>({finding_id:`f${i}`,file:file.file,rule_id:'1.1.1',disposition:'resolved_verified'}))})
  listHitlQueue.mockResolvedValue([])
  getScanRemediationDiffs.mockResolvedValue({items:[],total:0})
  getSourceStatus.mockResolvedValue({files:[]})
  getReleaseStatus.mockResolvedValue({documents:[]})
  const snapshot={batch_id:'batch'}
  const {root}=await mount({snapshot,connected:true})
  await act(async()=>vi.advanceTimersByTime(400))
  await act(async()=>root.render(createElement(RemediationLiveDocuments,{...props,snapshot,connected:true,refreshKey:1})))
  await act(async()=>vi.advanceTimersByTime(400))
  expect(getSourceStatus).toHaveBeenCalledTimes(1)
  expect(getReleaseStatus).toHaveBeenCalledTimes(2)
  await act(async()=>vi.advanceTimersByTime(30001))
  await act(async()=>root.render(createElement(RemediationLiveDocuments,{...props,snapshot,connected:true,refreshKey:2})))
  await act(async()=>vi.advanceTimersByTime(400))
  expect(getSourceStatus).toHaveBeenCalledTimes(2)
})
