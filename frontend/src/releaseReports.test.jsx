import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import ReleaseReports from './ReleaseReports.jsx'
afterEach(async()=>{await unmountAll();vi.useRealTimers()})
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
