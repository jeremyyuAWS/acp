import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Status from './AutomaticPublicationStatus.jsx'
import { releaseBatchDomain } from './releaseBatchProgress.js'
afterEach(unmountAll)
const batch = {available:true,authorization_id:'plan',run_id:'run',scope_id:'plan',revision:2,total:3,delivered:1,remaining:2,status:'publishing',
 buckets:{waiting:1,processing:1,published:1,failed:0,skipped:0,unclassified:0},
 file_membership:{'one.docx':'published','two.docx':'processing','three.docx':'waiting'}}
it('uses the full immutable plan for publication status without a manual publish action', async () => {
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<Status authorization={{id:'plan',status:'publishing',batch_progress:batch,destination_label:'SharePoint / Saved'}} />))
 expect(container.textContent).toContain('No Publish click is needed')
 expect(container.textContent).toContain('1 of 3 authorized copies delivered')
 expect([...container.querySelectorAll('button')].some(button=>/Publish batch|Approve eligible/.test(button.textContent))).toBe(false)
 expect(container.querySelector('[data-scope-id]').dataset.snapshotRevision).toBe('2')
})
it('rejects conflicting or unavailable saved-plan membership instead of borrowing request counts', () => {
 expect(releaseBatchDomain({...batch,file_membership:{'one.docx':'published'}})).toBeNull()
 expect(releaseBatchDomain({...batch,delivered:2})).toBeNull()
 expect(releaseBatchDomain({...batch,available:false})).toBeNull()
})
it('explains pending authorization and stopped publication without claiming delivery complete', async () => {
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<Status pending />))
 expect(container.textContent).toContain('Wait before starting another delivery')
 await act(async()=>root.render(<Status authorization={{id:'plan',status:'stopped',batch_progress:{...batch,status:'stopped'}}} />))
 expect(container.textContent).toContain('Automatic publishing is stopped')
 expect(container.textContent).not.toContain('All authorized copies are confirmed')
})
it('keeps remediation publication collapsed across polling without hiding publication progress elsewhere',async()=>{
 const {root,container}=createTestRoot()
 const auth={id:'plan',status:'publishing',batch_progress:batch,destination_label:'SharePoint / Saved'}
 await act(async()=>root.render(<Status authorization={auth} collapsed />))
 const disclosure=container.querySelector('details')
 expect(disclosure.open).toBe(false)
 expect(disclosure.querySelector('summary').textContent).toContain('1 of 3 delivered')
 expect(container.querySelector('[aria-label="Publication progress"]') || container.querySelector('.workflow-outcome-tiles')).not.toBeNull()
 disclosure.open=true
 await act(async()=>root.render(<Status authorization={{...auth,batch_progress:{...batch,revision:3}}} collapsed />))
 expect(container.querySelector('details').open).toBe(true)
 disclosure.open=false
 await act(async()=>root.render(<Status authorization={auth} collapsed />))
 expect(container.querySelector('details').open).toBe(false)
})

it('does not call a reconnect-blocked release active publication',async()=>{
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<Status authorization={{id:'plan',status:'blocked',requires_reconnect:true,batch_progress:batch}}/>))
 expect(container.textContent).toContain('Delivery is paused')
 expect(container.textContent).toContain('no new scan or approval is needed')
 expect(container.textContent).not.toContain('No Publish click is needed')
})
