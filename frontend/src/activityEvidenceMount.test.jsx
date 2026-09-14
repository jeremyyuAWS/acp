import React,{act} from 'react'
import {createRoot} from 'react-dom/client'
import {expect,it,vi} from 'vitest'
const api=vi.hoisted(()=>({read:vi.fn(),copy:vi.fn(),evidence:vi.fn()}))
vi.mock('./api.js',async original=>({...await original(),getRemediationActivityEvidence:api.read,downloadRemediationActivitySavedCopy:api.copy,downloadRemediationActivityEvidence:api.evidence}))
import {Activity} from './RemediationOpsPanel.jsx'
import {addRemediationEvent} from './remediationEventFeed.js'
it('loads the mounted event evidence lazily and downloads only that recorded event copy',async()=>{
 const sha='a'.repeat(64),event=addRemediationEvent([],{kind:'remediate.verified',document:'report.docx',detail:{fixes:1,evidence_id:'123456abcdef',artifact_sha256:sha,criteria:['1.3.1']}},8)[0]
 api.read.mockResolvedValue({available:true,artifact_sha256:sha,criteria:['1.3.1'],changes:[{criterion:'1.3.1',location:'Paragraph 4',before:'Body text',after:'Heading 1',verification:'verified'}],verification:{status:'verified',artifact_sha256:sha},saved_copy:{matches_event:true,download_url:'/scans/scan-1/remediation/activity/8/copy'}})
 const host=document.createElement('div');document.body.append(host);const root=createRoot(host)
 try{
  await act(()=>root.render(<Activity scanId="scan-1" events={[event]}/>));expect(api.read).not.toHaveBeenCalled()
  const details=host.querySelector('.activity-event-details details')
  await act(async()=>{details.open=true;details.dispatchEvent(new Event('toggle',{bubbles:true}));await Promise.resolve()})
  expect(api.read).toHaveBeenCalledWith('scan-1','8');expect(host.textContent).toContain('Paragraph 4');expect(host.textContent).toContain('Heading 1')
  await act(async()=>[...host.querySelectorAll('button')].find(button=>button.textContent==='Download This Saved Copy').click())
  expect(api.copy).toHaveBeenCalledWith('scan-1','8')
 }finally{await act(()=>root.unmount());host.remove()}
})
