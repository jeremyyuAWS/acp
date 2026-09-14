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
it('shows criterion and actionable source-edit guidance before opening a suggestion', async () => {
 const c=await mount({file:{file:'untagged.pdf'},items:[{id:2,file:'untagged.pdf',rule_id:'WCAG_1_3_1',rule_name:'Info and Relationships',suggested_value:'Heading map'}]})
 expect(c.textContent).toContain('SC 1.3.1')
 expect(c.textContent).toContain('Next step:')
 expect(c.textContent).toContain('ACP cannot write this PDF heading or table structure')
})
it('lets reviewers choose each real evidence location and focuses its preview', async () => {
 const c=await mount({items:[{id:2,file:'sample.docx',rule_id:'1.1.1',evidence:[{page:2,locator:'word/document.xml#rId2'},{page:7,locator:'word/document.xml#rId7'}]}]})
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Show page 7').click())
 expect(c.querySelector('[data-testid="preview"]').dataset.page).toBe('7')
 expect(c.querySelector('[data-testid="preview"]').dataset.locator).toBe('word/document.xml#rId7')
 expect(document.activeElement).toBe(c.querySelector('.graph-findings-preview'))
})
it('does not mark duplicate change rows selected together', async () => {
 const {getFileRemediationDiffs}=await import('./api.js')
 getFileRemediationDiffs.mockResolvedValueOnce([{rule_id:'1.3.1',before:'First',after:'Heading 1'},{rule_id:'1.3.1',before:'Second',after:'Heading 2'}])
 const c=await mount()
 await act(async()=>c.querySelectorAll('.graph-finding-select')[1].click())
 expect([...c.querySelectorAll('.graph-finding-select')].map(b=>b.getAttribute('aria-pressed'))).toEqual(['false','true'])
})
it('distinguishes unavailable change evidence from zero changes and supports retry', async () => {
 const {getFileRemediationDiffs}=await import('./api.js')
 getFileRemediationDiffs.mockRejectedValueOnce(new Error('network unavailable'))
 const c=await mount()
 expect(c.querySelector('[role="alert"]').textContent).toContain('does not mean the document has no changes')
 expect(c.textContent).not.toContain('No change evidence is available.')
 expect(getFileRemediationDiffs).toHaveBeenLastCalledWith('scan','sample.docx',{strict:true})
 await act(async()=>[...c.querySelectorAll('button')].find(b=>b.textContent==='Retry loading changes').click())
 expect(c.querySelector('[role="alert"]')).toBeNull()
 expect(c.textContent).toContain('Heading 1')
})
