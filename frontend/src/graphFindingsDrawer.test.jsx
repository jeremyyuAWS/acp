import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
vi.mock('./Drawer.jsx', () => ({default: ({children}) => <div>{children}</div>}))
vi.mock('./Thumbnail.jsx', () => ({default: props => <div data-testid="preview" data-page={props.page} data-locator={props.locator || ''} />}))
vi.mock('./AccessibilityStatus.jsx', () => ({default: () => <div>Coverage detail</div>}))
vi.mock('./EvidenceCard.jsx', () => ({default: ({onAct}) => <button onClick={() => onAct(1, 'approved')}>Apply recorded suggestion</button>}))
vi.mock('./api.js', () => ({getFileRemediationDiffs: vi.fn(async () => [{rule_id:'1.3.1',before:'Body text',after:'Heading 1',verified:true}]),downloadRemediated:vi.fn()}))
import GraphFindingsDrawer from './GraphFindingsDrawer.jsx'
afterEach(unmountAll)
const file={file:'sample.docx',remediated_at:'now',issues:[{wcag:'SC_1_1_1',detail:'Image needs alt text',page:3,locator:'word/document.xml#rId3'}]}
async function mount(props={}) {
 const {root,container}=createTestRoot()
 await act(async()=>root.render(createElement(GraphFindingsDrawer,{file,scanId:'scan',...props})))
 return container
}
it('shows recorded before and after changes and collapses coverage by default',async()=>{
 const c=await mount()
 expect(c.textContent).toContain('Body text')
 expect(c.textContent).toContain('Heading 1')
 expect(c.textContent).toContain('Verified fix')
 expect(c.querySelector('details').open).toBe(false)
 expect(c.textContent).not.toContain('/100')
})
it('locates selected findings only using recorded pages and locators',async()=>{
 const c=await mount()
 await act(async()=>[...c.querySelectorAll('[role="tab"]')].find(b=>b.textContent==='All findings').click())
 await act(async()=>c.querySelector('.graph-finding-select').click())
 expect(c.querySelector('[data-testid="preview"]').dataset.page).toBe('3')
 expect(c.querySelector('[data-testid="preview"]').dataset.locator).toBe('word/document.xml#rId3')
 expect(c.textContent).toContain('Findings from the original scan')
})
it('keeps historical suggestions read-only and unsupported PDF tagging manual',async()=>{
 const c=await mount({file:{file:'untagged.pdf'},items:[{id:1,file:'untagged.pdf',rule_id:'1.3.1',suggested_value:'Heading map'}],readOnly:true})
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='View editing guidance').click())
 expect(c.textContent).toContain('cannot create the missing PDF structure tree')
 expect(c.textContent).not.toContain('Apply recorded suggestion')
})
it('wires supported review actions to the durable decision callback',async()=>{
 const onAct=vi.fn()
 const c=await mount({items:[{id:1,file:'sample.docx',rule_id:'1.1.1'}],onAct})
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Review recorded suggestion').click())
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Apply recorded suggestion').click())
 expect(onAct).toHaveBeenCalledWith(1,'approved')
})
