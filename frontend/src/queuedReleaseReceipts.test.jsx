import { it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
import { createTestRoot, unmountAll } from './testRoots.js'

// Drive delivery is confirmed by durable receipts, including after navigation.
const publishAllFiles = vi.fn(() => Promise.resolve({ published: [] }))
const listHitlQueue = vi.fn(() => Promise.resolve([]))
const getReleaseStatus = vi.fn().mockResolvedValue({release_id:null})
const getSettings = vi.fn(() => Promise.resolve({ drive_mirror_enabled: false, drive_mirror_folder: 'Remediated' }))
const putMyReleaseTemplates = vi.fn((templates) => Promise.resolve({ release_templates: templates }))
vi.mock('./api.js', () => ({
  getAutomaticRelease: vi.fn().mockResolvedValue({authorization:null}),
  getReleaseReports: vi.fn().mockResolvedValue({status:'not_started',reports:[]}), retryReleaseReports: vi.fn(), downloadReleaseReport: vi.fn(),
  openReport: vi.fn(), publishFile: vi.fn(() => Promise.resolve({})),
  publishAllFiles: (...a) => publishAllFiles(...a),
  getReleaseStatus: (...a) => getReleaseStatus(...a),
  listReleaseHistory: vi.fn(() => Promise.resolve({ releases: [] })),
  getReleaseManifest: vi.fn(() => Promise.resolve({ manifest: {} })),
  listHitlQueue: (...args) => listHitlQueue(...args),
  getSettings: (...a) => getSettings(...a),
  putMyReleaseTemplates: (...a) => putMyReleaseTemplates(...a),
  getSourceStatus: vi.fn(() => Promise.resolve({ files: [], stale_count: 0 })),
  rescoreFile: vi.fn(() => Promise.resolve({})),
  previewReleaseDestination: vi.fn(() => Promise.resolve({ can_release: true, documents: [] })),
  downloadReleasePackage: vi.fn(() => Promise.resolve()),
}))
// Exercise Publish authority while keeping unrelated document views outside this fixture.
vi.mock('./FileDrawer.jsx', () => ({ default: () => null }))
vi.mock('./ScopeBanner.jsx', () => ({ default: () => null }))
vi.mock('./SearchFilterBar.jsx', () => ({
  default: () => null,
  useSearchFilter: () => ({ active: false, clear: () => {} }),
  matchesFilters: () => () => true,
}))
vi.mock('./remediableScope.js', () => ({
  documentSelection: () => ({}),
  documentScopeSentence: () => '',
  documentsInSelection: (files) => files || [],
}))

vi.mock('./ReleaseQuickActions.jsx', () => ({default: ({onReady,ready}) => <button onClick={() => onReady(ready.map(f=>f.file))}>Test publish ready</button>}))
vi.mock('./RemediationLiveDocuments.jsx', () => ({default: () => null}))
const { default: Publish } = await import('./Publish.jsx')
const { getAutomaticRelease } = await import('./api.js')

afterEach(async () => { await unmountAll(); vi.useRealTimers(); vi.clearAllMocks(); getAutomaticRelease.mockReset().mockResolvedValue({authorization:null}); getReleaseStatus.mockReset().mockResolvedValue({release_id:null}); publishAllFiles.mockReset(); listHitlQueue.mockResolvedValue([]) })
const flush = async () => { for (let k = 0; k < 5; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(Publish, props)) })
  await flush()
  return container
}
const verified = (file, over = {}) => ({ file, compliant: true, remediated_at: '2026-07-31T00:00:00Z', score: 100, department: 'D', sourceName: 'S', ...over })
const run = { id: 'scan1', files: 3, certifiable: 2 }


const props={run:{...run,source:'drive'},me:{email:'first@example.com'},files:[verified('a.pdf',{corrected_sha256:'v1'})]}
it.each(['waiting','processing','blocked'])('uses saved Q3 %s permission instead of manually dispatching covered copies',async status=>{
 getAutomaticRelease.mockResolvedValue({authorization:{id:'auto',status,files:['a.pdf'],allow_remaining_issues:true}})
 const c=await mount({...props,embedded:true})
 expect(c.textContent).toContain('Automatic publishing is on')
 expect(c.textContent).toContain('1 ready')
 expect([...c.querySelectorAll('button')].some(b=>b.textContent==='Publish 1 saved copy')).toBe(false)
 expect(publishAllFiles).not.toHaveBeenCalled()
})
const receipt=status=>({release_id:'r',documents:[{file:'a.pdf',status,corrected_checksum:'v1',published_at:status==='published'?'2026-09-12':null}]})
const start=async c=>act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Test publish ready').click())
it('follows queued Drive receipts without publishing twice',async()=>{
 const onPublish=vi.fn(),c=await mount({...props,onPublish});vi.useFakeTimers()
 publishAllFiles.mockResolvedValue({queued:true,release_id:'r',published:[{file:'a.pdf',status:'queued'}]})
 getReleaseStatus.mockResolvedValueOnce(receipt('running')).mockResolvedValue(receipt('published'))
 await start(c);expect(onPublish).not.toHaveBeenCalled()
 await act(async()=>vi.advanceTimersByTimeAsync(2000))
 expect(onPublish).toHaveBeenCalledExactlyOnceWith('a.pdf');expect(publishAllFiles).toHaveBeenCalledTimes(1)
 expect(publishAllFiles.mock.calls[0][3].expectedArtifacts).toEqual({'a.pdf':'v1'})
 expect(c.textContent).toContain('1 corrected copy released')
})
it.each(['scan','owner','unmount'])('ignores receipt responses after %s changes',async change=>{
 const onPublish=vi.fn(),{container,root}=createTestRoot()
 await act(async()=>root.render(createElement(Publish,{...props,onPublish})));await flush()
 let resolve;publishAllFiles.mockResolvedValue({queued:true,release_id:'r',published:[]})
 getReleaseStatus.mockImplementationOnce(()=>new Promise(r=>{resolve=r})).mockResolvedValue({release_id:null})
 await start(container)
 await act(async()=>change==='unmount'?root.unmount():root.render(createElement(Publish,{...props,onPublish,...(change==='scan'?{run:{...props.run,id:'other'}}:{me:{email:'second@example.com'}})})))
 await act(async()=>resolve(receipt('published')))
 expect(onPublish).not.toHaveBeenCalled();expect(publishAllFiles).toHaveBeenCalledTimes(1)
})
it('stops queued polling timers on unmount',async()=>{
 const {container,root}=createTestRoot()
 await act(async()=>root.render(createElement(Publish,props)));await flush();vi.useFakeTimers()
 publishAllFiles.mockResolvedValue({queued:true,release_id:'r',published:[]})
 getReleaseStatus.mockResolvedValue(receipt('running'));await start(container)
 const calls=getReleaseStatus.mock.calls.length
 await act(async()=>root.unmount());await act(async()=>vi.advanceTimersByTimeAsync(6000))
 expect(getReleaseStatus).toHaveBeenCalledTimes(calls)
})
it('refreshes status after a read failure without retrying the queued publication',async()=>{
 const c=await mount(props)
 publishAllFiles.mockResolvedValue({queued:true,release_id:'r',published:[{file:'a.pdf',status:'queued'}]})
 getReleaseStatus.mockRejectedValueOnce(new Error('Status connection unavailable'))
 await start(c)
 expect(c.textContent).toContain('Delivery is queued, but its progress could not be refreshed.')
 getReleaseStatus.mockResolvedValue(receipt('published'))
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Refresh delivery status').click())
 expect(publishAllFiles).toHaveBeenCalledTimes(1)
 expect(c.textContent).toContain('1 corrected copy released')
})
it('uses authoritative queued delivery in the embedded Remediate card',async()=>{
 const onPublish=vi.fn(),onOpenDetails=vi.fn(),c=await mount({...props,embedded:true,onPublish,onOpenDetails})
 expect(c.textContent).toContain('Publish corrected copies');expect(publishAllFiles).not.toHaveBeenCalled()
 vi.useFakeTimers();publishAllFiles.mockResolvedValue({queued:true,release_id:'r',published:[{file:'a.pdf',status:'queued'}]})
 getReleaseStatus.mockResolvedValueOnce(receipt('running')).mockResolvedValue(receipt('published'))
 const button=[...c.querySelectorAll('button')].find(b=>b.textContent==='Publish 1 saved copy')
 await act(async()=>{button.click();button.click()})
 expect(publishAllFiles).toHaveBeenCalledTimes(1);expect(onPublish).not.toHaveBeenCalled()
 await act(async()=>vi.advanceTimersByTimeAsync(2000))
 expect(onPublish).toHaveBeenCalledExactlyOnceWith('a.pdf');expect(c.textContent).toContain('1 published')
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Release details').click())
 expect(onOpenDetails).toHaveBeenCalledOnce()
})
it('keeps embedded publishing disabled in read-only views',async()=>{
 const c=await mount({...props,embedded:true,readOnly:true})
 expect([...c.querySelectorAll('button')].find(b=>b.textContent==='Publish 1 saved copy').disabled).toBe(true)
 expect(c.querySelector('input[type="checkbox"]').disabled).toBe(true)
 expect(publishAllFiles).not.toHaveBeenCalled()
})
it('includes saved copies with remaining work only after the user chooses it',async()=>{
 const c=await mount({...props,embedded:true,files:[verified('a.pdf',{compliant:false,corrected_sha256:'v1'})]})
 expect(c.textContent).toContain('0 ready');expect(publishAllFiles).not.toHaveBeenCalled()
 await act(async()=>c.querySelector('input[type="checkbox"]').click())
 expect(c.textContent).toContain('1 ready');expect(publishAllFiles).not.toHaveBeenCalled()
 publishAllFiles.mockResolvedValue({published:[]})
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Publish 1 saved copy').click())
 expect(publishAllFiles.mock.calls[0][3]).toMatchObject({allowRemainingIssues:true,expectedArtifacts:{'a.pdf':'v1'}})
})

it('restores interrupted legacy delivery without replaying or calling it active', async () => {
 getReleaseStatus.mockResolvedValue({...receipt('interrupted'),status:'attention'})
 const c=await mount(props)
 expect(c.textContent).toContain('Delivery not confirmed')
 expect(c.textContent).toContain('1 need attention')
 expect(c.textContent).not.toContain('being released.')
 expect(publishAllFiles).not.toHaveBeenCalled()
})

it('shows a read-only reconstruction diagnosis without overwriting the saved outcome or retrying', async () => {
 const recovery_explanation='This PDF has no accessibility tag tree and needs document reconstruction.'
 getReleaseStatus.mockResolvedValue({release_id:'r',status:'attention',documents:[{file:'a.pdf',status:'failed',failure_category:'no_corrected_copy',explanation:'No saved copy.',recovery_explanation}]})
 const c=await mount({...props,files:[verified('a.pdf',{compliant:false,remediated_at:null,corrected_sha256:null})]})
 expect(c.textContent).toContain('No saved copy')
 expect(c.textContent).toContain(recovery_explanation)
 expect(publishAllFiles).not.toHaveBeenCalled()
})
