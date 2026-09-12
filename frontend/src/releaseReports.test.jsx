import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import ReleaseReports from './ReleaseReports.jsx'
afterEach(async()=>{await unmountAll();vi.useRealTimers()})
it('reloads reports when the release changes with the same published count', async () => {
 const read=vi.fn().mockResolvedValueOnce({status:'completed',reports:[{name:'old.pdf'}]}).mockResolvedValue({status:'completed',reports:[{name:'new.pdf'}]})
 const {root,container}=createTestRoot()
 await act(async()=>root.render(createElement(ReleaseReports,{scanId:'scan',releaseId:'old',publishedCount:4,read})))
 expect(container.textContent).toContain('old.pdf')
 await act(async()=>root.render(createElement(ReleaseReports,{scanId:'scan',releaseId:'new',publishedCount:4,read})))
 expect(read).toHaveBeenCalledTimes(2)
 expect(container.textContent).toContain('new.pdf')
 expect(container.textContent).not.toContain('old.pdf')
})
async function mount(props={}) {const {root,container}=createTestRoot();await act(async()=>root.render(createElement(ReleaseReports,{scanId:'scan',...props})));return container}
it('shows saved report links without claiming compliance',async()=>{
 const read=vi.fn().mockResolvedValue({status:'completed',bundle_id:'b',reports:[{name:'Scan summary.html',url:'https://example.com/report',download_url:'/scans/scan/release/reports/b/0'}]})
 const download=vi.fn().mockResolvedValue();const c=await mount({read,download})
 expect(c.querySelector('a').href).toBe('https://example.com/report');expect(c.textContent).toContain('does not certify accessibility')
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Download').click())
 expect(download).toHaveBeenCalledWith('scan','b',0,'Scan summary.html')
})
it('allows report-only retry when document publication has already completed',async()=>{
 const read=vi.fn().mockResolvedValueOnce({status:'failed',reports:[]}).mockResolvedValue({status:'completed',reports:[]})
 const retry=vi.fn().mockResolvedValue({});const c=await mount({read,retry})
 expect(c.textContent).toContain('Files may be published')
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Retry report delivery').click())
 expect(retry).toHaveBeenCalledWith('scan');expect(c.textContent).toContain('Reports are ready to download')
})
it('polls in-flight reports and stops after completion',async()=>{
 vi.useFakeTimers();const read=vi.fn().mockResolvedValueOnce({status:'queued',reports:[]}).mockResolvedValue({status:'completed',reports:[]})
 const c=await mount({read});expect(c.textContent).toContain('Preparing and saving')
 await act(async()=>vi.advanceTimersByTimeAsync(10000));expect(read).toHaveBeenCalledTimes(2)
 await act(async()=>vi.advanceTimersByTimeAsync(20000));expect(read).toHaveBeenCalledTimes(2)
})
it('keeps missing reports truthful without background polling',async()=>{
 vi.useFakeTimers();const read=vi.fn().mockResolvedValue({status:'not_started',reports:[]});const c=await mount({read})
 expect(c.textContent).toContain('reporting enabled');await act(async()=>vi.advanceTimersByTimeAsync(30000));expect(read).toHaveBeenCalledOnce()
})

it('waits briefly for report creation after the last file publishes',async()=>{
 vi.useFakeTimers();const read=vi.fn().mockResolvedValue({status:'not_started',reports:[]})
 await mount({read,publishedCount:2});await act(async()=>vi.advanceTimersByTimeAsync(130000));expect(read).toHaveBeenCalledTimes(12)
})
it('offers a report-only PDF refresh for completed legacy reports', async () => {
 const read = vi.fn().mockResolvedValue({ status: 'completed', reports: [{ name: 'old.html', content_type: 'text/html' }] })
 const retry = vi.fn().mockResolvedValue({})
 const c = await mount({ read, retry })
 await act(async () => [...c.querySelectorAll('button')].find(b => b.textContent === 'Generate PDF reports').click())
 expect(retry).toHaveBeenCalledWith('scan')
})

it('places scan reports beneath the outcomes intro and version-matched per-file actions beneath the published copy', async () => {
 const {default: Documents}=await import('./ReleaseCompletionDocuments.jsx')
 const files=[{file:'a.pdf',remediated_at:'now'},{file:'b.pdf',remediated_at:'now'}]
 const digest='sha256:a';const read=vi.fn().mockResolvedValue({status:'completed',bundle_id:'bundle',scan_id:'scan',release_id:'release',reports:[
   {name:'summary.pdf',report_kind:'scan_summary',url:'https://example.com/summary',download_url:'/download/0'},
   {name:'a-changes.pdf',report_kind:'changes',file:'a.pdf',artifact_digest:digest,url:'https://example.com/a',download_url:'/download/1'},
   {name:'b-checklist.pdf',report_kind:'checklist',file:'b.pdf',artifact_digest:'sha256:old',url:'https://example.com/b',download_url:'/download/2'},
 ]})
 const download=vi.fn();const states=files.map(()=>({status:'released',label:'Published',reason:'Delivered'}))
 const results={'a.pdf':{status:'published',artifact_digest:digest,published_url:'https://example.com/copy'},'b.pdf':{status:'published',artifact_digest:'sha256:new'}}
 const c=await mount({read,download,files,results,releaseId:'release',children:({reportSummary,reportsByFile})=>createElement(Documents,{files,states,results,reportSummary,reportsByFile})})
 const section=c.querySelector('[aria-label="Publication outcomes"]')
 expect(section.children[1].textContent).toContain('Saved copies, verification')
 expect(section.children[2].getAttribute('aria-label')).toBe('Release reports')
 const rows=[...section.querySelectorAll('tbody tr')]
 expect(rows[0].querySelector('td:last-child').textContent).toContain('Open published copya-changes.pdfDownload')
 expect(rows[1].textContent).not.toContain('b-checklist.pdf')
 expect(section.querySelector('[aria-label="Release reports"]').textContent).toContain('summary.pdf')
 expect(section.querySelector('[aria-label="Release reports"]').textContent).toContain('b-checklist.pdf')
 expect(section.textContent).toContain('Document version could not be matched')
 expect(section.querySelectorAll('a[href="https://example.com/a"]')).toHaveLength(1)
 await act(async()=>rows[0].querySelector('button').click())
 expect(download).toHaveBeenCalledWith('scan','bundle',1,'a-changes.pdf')
})
it('does not attach reports from another release, another scan or absent version metadata to document rows', async () => {
 for (const identity of [{scan_id:'other',release_id:'release'},{scan_id:'scan',release_id:'other'},{}]) {
   const read=vi.fn().mockResolvedValue({status:'completed',bundle_id:'b',...identity,reports:[{name:'a.pdf',report_kind:'changes',file:'a.pdf',artifact_digest:'d',download_url:'/d'}]})
   const child=vi.fn().mockReturnValue(createElement('span',null,'layout'))
   await mount({read,files:[{file:'a.pdf'}],results:{'a.pdf':{status:'published',artifact_digest:'d'}},releaseId:'release',children:child})
   expect(child.mock.lastCall[0].reportsByFile).toEqual({})
 }
})
it('deliberately retires the duplicate per-file receipt list', async () => {
 const {readFileSync}=await import('node:fs')
 const source=readFileSync('src/Publish.jsx','utf8')
 expect(source).toContain('export function RetiredDeliveryReceiptFiles')
 expect(source).not.toMatch(/<RetiredDeliveryReceiptFiles\b/)
 expect(source).not.toMatch(/publishedEntries\.map\(\(entry\)/)
})
it('matches native tracked-change companions and evidence to their exact delivered version without a PDF regeneration loop',async()=>{
 const files=[{file:'policy.docx'}],results={'policy.docx':{status:'published',artifact_digest:'sha256:corrected'}}
 const reports=[{name:'policy.tracked-changes.docx',report_kind:'tracked_changes',content_type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',file:'policy.docx',artifact_digest:'sha256:corrected',download_url:'/download/0'},
 {name:'policy.changes.json',report_kind:'tracked_changes_evidence',content_type:'application/json',file:'policy.docx',artifact_digest:'sha256:corrected',download_url:'/download/1'}]
 const read=vi.fn().mockResolvedValue({status:'completed',scan_id:'scan',release_id:'release',bundle_id:'bundle',reports}),download=vi.fn().mockResolvedValue()
 const c=await mount({files,results,releaseId:'release',read,download,children:({reportSummary,reportsByFile})=>createElement('div',null,reportSummary,createElement('section',{'data-file':'policy.docx'},reportsByFile['policy.docx']))})
 const row=c.querySelector('[data-file]');expect(row.textContent).toContain('Tracked changes (Word companion)');expect(row.textContent).toContain('Change evidence (JSON)')
 expect(c.textContent).not.toContain('Generate PDF reports');expect(c.textContent).not.toContain('version could not be matched')
 await act(async()=>[...row.querySelectorAll('button')].find(b=>b.textContent==='Download Word companion').click())
 expect(download).toHaveBeenCalledWith('scan','bundle',0,'policy.tracked-changes.docx')
 await act(async()=>[...row.querySelectorAll('button')].find(b=>b.textContent==='Download change evidence').click())
 expect(download).toHaveBeenCalledWith('scan','bundle',1,'policy.changes.json')
})
it('retains mismatched native assets in the report header and only regenerates printable legacy HTML',async()=>{
 const reports=[{name:'policy.tracked.docx',report_kind:'tracked_changes',content_type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',file:'policy.docx',artifact_digest:'sha256:old'},{name:'summary.html',report_kind:'scan_summary',content_type:'text/html'}]
 const read=vi.fn().mockResolvedValue({status:'completed',scan_id:'scan',release_id:'release',reports}),child=vi.fn(({reportSummary})=>reportSummary)
 const c=await mount({read,files:[{file:'policy.docx'}],results:{'policy.docx':{status:'published',artifact_digest:'sha256:new'}},releaseId:'release',children:child})
 expect(child.mock.lastCall[0].reportsByFile).toEqual({});expect(c.textContent).toContain('Document version could not be matched')
 expect([...c.querySelectorAll('button')].some(b=>b.textContent==='Generate PDF reports')).toBe(true)
})
