import React,{act} from 'react'
import {createRoot} from 'react-dom/client'
import {afterEach,expect,it} from 'vitest'
import {Activity} from './RemediationOpsPanel.jsx'
import {addRemediationEvent,remediationEventLine} from './remediationEventFeed.js'
let root,host
const rows=n=>Array.from({length:n},(_,i)=>({key:String(n-i),id:String(n-i),kind:'remediate.document_completed',tone:'success',line:`Update ${n-i}`,documentKey:'same'}))
afterEach(async()=>{if(root)await act(()=>root.unmount());host?.remove();root=null})
async function render(events){if(!root){host=document.createElement('div');document.body.append(host);root=createRoot(host)}await act(()=>root.render(<Activity events={events}/>))}
it('keeps all 140 updates and prepends without replacing existing rows',async()=>{
 await render(rows(140));const list=host.querySelector('ol'),oldest=list.lastElementChild
 expect(list.children).toHaveLength(140);await render(rows(141))
 expect(host.querySelector('ol')).toBe(list);expect(list.lastElementChild).toBe(oldest)
 expect(list.firstElementChild.textContent).toContain('Update 141')
 expect(host.querySelector('input[aria-label="Scroll activity history"]')).not.toBeNull()
})
it('anchors older activity when a new update arrives',async()=>{
 await render(rows(5));const list=host.querySelector('ol');let size=5
 list.getBoundingClientRect=()=>({top:0})
 Object.defineProperty(list,'clientHeight',{value:120});Object.defineProperty(list,'scrollHeight',{get:()=>size*60})
 for(const row of list.children)row.getBoundingClientRect=()=>{const i=[...list.children].indexOf(row);return{top:i*60-list.scrollTop,bottom:(i+1)*60-list.scrollTop}}
 list.scrollTop=120;await act(()=>list.dispatchEvent(new Event('scroll',{bubbles:true})))
 size=6;await render(rows(6));expect(list.scrollTop).toBe(180)
 await act(()=>[...host.querySelectorAll('button')].find(b=>b.textContent.includes('Latest')).click());expect(list.scrollTop).toBe(0)
})
it('retains merged history and deduplicates sequence IDs',()=>{
 let history=[];for(let id=1;id<=240;id++)history=addRemediationEvent(history,{kind:'remediate.document_completed',document:'a.docx'},id)
 expect(history).toHaveLength(240);expect(addRemediationEvent(history,{kind:'remediate.document_completed'},40)).toBe(history)
})
it('shows the recorded AI model and zone without a verification claim',()=>{
 const event={kind:'remediate.ai_request_started',document:'a.docx',detail:{processing_zone:'local',provider:'ollama',model:'moondream:latest',prompt:'private'}}
 expect(remediationEventLine(event)).toBe('Local AI · moondream:latest (ollama) · Request sent for a.docx')
 expect(remediationEventLine({...event,kind:'remediate.ai_request_finished',detail:{processing_zone:'cloud',model:'gpt-4.1',status:'failed'}})).toContain('Cloud AI · gpt-4.1 · Request failed')
 expect(remediationEventLine({...event,detail:{}})).toContain('Model not recorded')
})
