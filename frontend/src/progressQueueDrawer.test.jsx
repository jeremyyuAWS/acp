import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import ProgressQueueDrawer from './ProgressQueueDrawer.jsx'
afterEach(unmountAll)
async function mount(props) {const {root,container}=createTestRoot();await act(async()=>root.render(createElement(ProgressQueueDrawer,props)));return{root,container}}
it('searches named queues, retains blocked reasons and updates live membership', async()=>{
 const props={title:'Needs attention',files:[{file:'broken.pdf',status:'blocked',reason:'Password required'},{file:'ready.docx',status:'attention',findingCount:3}],onClose:vi.fn()}
 const {root,container}=await mount(props)
 expect(container.querySelector('[role="dialog"]').getAttribute('aria-modal')).toBe('true')
 expect(container.textContent).toContain('Password required')
 const search=container.querySelector('input');await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(search,'broken');search.dispatchEvent(new Event('input',{bubbles:true}))})
 expect(container.querySelectorAll('article')).toHaveLength(1)
 await act(async()=>root.render(createElement(ProgressQueueDrawer,{...props,files:[]})))
 expect(container.textContent).toContain('No files match your search.')
})
it('traps keyboard focus, closes with Escape and restores the opener',async()=>{
 const opener=document.createElement('button');document.body.append(opener);opener.focus()
 const onClose=vi.fn();const {root,container}=await mount({title:'Published',files:[],onClose})
 const close=container.querySelector('button'),last=container.querySelector('[aria-label="Queue files"]')
 expect(document.activeElement).toBe(close)
 await act(async()=>close.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true})))
 expect(document.activeElement).toBe(last)
 await act(async()=>last.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})))
 expect(onClose).toHaveBeenCalledOnce()
 await act(async()=>root.render(null));expect(document.activeElement).toBe(opener);opener.remove()
})
it('distinguishes an empty queue from unavailable evidence',async()=>{
 const {root,container}=await mount({title:'Processing',files:[]})
 expect(container.textContent).toContain('No files are currently in this queue.')
 await act(async()=>root.render(<ProgressQueueDrawer title="Processing" files={[]} error="Saved queue unavailable"/>))
 expect(container.querySelector('[role="alert"]').textContent).toBe('Saved queue unavailable')
 expect(container.textContent).not.toContain('No files are currently in this queue.')
})
