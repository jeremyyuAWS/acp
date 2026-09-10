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
