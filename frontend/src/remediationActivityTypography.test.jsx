import { act } from 'react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { createTestRoot, unmountAll } from './testRoots.js'
import { Activity, RemediationActivityPanel } from './RemediationOpsPanel.jsx'
import RemediationCategoryPill from './RemediationCategoryPill.jsx'
let previousActEnvironment
beforeEach(()=>{previousActEnvironment=globalThis.IS_REACT_ACT_ENVIRONMENT;globalThis.IS_REACT_ACT_ENVIRONMENT=true})
afterEach(async()=>{await unmountAll();globalThis.IS_REACT_ACT_ENVIRONMENT=previousActEnvironment})
const name='Very_long_document_name_with_no_spaces_and_a_repeated_identifier_123456789012345678901234567890.docx'
const events=[{key:'latest',documentKey:'doc',tone:'success',occurredAt:'2026-09-13T12:00:00Z',line:`2 fixes independently verified for ${name}`},
  {key:'previous',documentKey:'doc',tone:'attention',occurredAt:'2026-09-13T12:00:00Z',line:`Corrected copy of ${name} saved in ACP · source delivery is unavailable`}]
it('uses a queue icon for acceptance without suggesting verification', async () => {
  const {root,container}=createTestRoot()
  await act(async()=>root.render(<Activity events={[{key:'accepted',kind:'remediate.accepted',tone:'info',line:'Remediation accepted for 4 documents'}]} />))
  const icon=container.querySelector('[data-activity-icon="accepted"]')
  expect(icon.tagName.toLowerCase()).toBe('svg')
  expect(icon.parentElement.getAttribute('aria-hidden')).toBe('true')
  expect(container.textContent).toContain('Remediation accepted for 4 documents')
  expect(container.querySelector('.remops-activity-success')).toBeNull()
})
it('gives Remaining its own compact pill and honest finding-count label', async () => {
  const {root,container}=createTestRoot()
  await act(async()=>root.render(<RemediationCategoryPill category="remaining" count={1} />))
  const pill=container.querySelector('.remediation-category-pill--remaining')
  expect(pill.getAttribute('aria-label')).toBe('Remaining: 1 findings')
  expect(pill.textContent).toBe('Remaining 1')
  expect(pill.title).toContain('without a verified fix')
  expect(readFileSync('src/remediation-category-pills.css','utf8')).toMatch(/--remaining\s*\{[^}]*#78295f[^}]*#f8e5f3/)
  expect(readFileSync('src/RemediationLiveDocuments.jsx','utf8')).toContain("category === 'remaining' ? <RemediationCategoryPill")
})
it('uses the same shared mono entry selectors for standalone and run activity with preserved document history', async () => {
  const {root,container}=createTestRoot()
  await act(async()=>root.render(<><Activity events={events}/><RemediationActivityPanel snapshot={{scan_id:'scan',batch_id:'batch',state:'processing'}} events={events}/></>))
  const feeds=container.querySelectorAll('.remops-activity')
  expect(feeds).toHaveLength(2)
  for (const feed of feeds) {
    await act(async()=>[...feed.querySelectorAll('button')].find(button=>button.textContent==='Group by document').click())
    expect(feed.querySelector('.remops-activity-event > span:last-child').textContent).toContain(name)
    expect(feed.querySelector('time').dateTime).toBe('2026-09-13T12:00:00Z')
    const details=feed.querySelector('details');details.open=true
    expect(details.querySelector('li').textContent).toContain(name)
    expect(feed.querySelector('.remops-delivery-tag').textContent).toBe('source delivery is unavailable')
    expect(feed.querySelector('h3').textContent).toBe('Live activity')
  }
})
it('matches Release monospace token while keeping long names wrapped and status tags in UI font', () => {
  const activity=readFileSync('src/remediation-ops-panel.css','utf8')
  const release=readFileSync('src/release-completion-documents.css','utf8')
  expect(release).toContain('font-family:var(--font-mono')
  expect(activity).toMatch(/\.remops-activity-event>span:last-child\s*\{[^}]*font-family:var\(--font-mono,[^}]*font-size:13px;[^}]*min-width:0;overflow-wrap:anywhere/)
  expect(activity).toMatch(/\.remops-activity-event time\s*\{[^}]*font-family:var\(--font-mono/)
  expect(activity).toMatch(/\.remops-activity details li\s*\{[^}]*font-family:var\(--font-mono/)
  expect(activity).toMatch(/\.remops-delivery-tag\s*\{[^}]*font-family:var\(--font-ui/)
})

it('keeps older retained activity keyboard-reachable in a bounded scrolling list', async()=>{
 const {root,container}=createTestRoot()
 const history=Array.from({length:25},(_,i)=>({key:String(i),documentKey:String(i),tone:'success',line:`Saved document ${i}`}))
 await act(async()=>root.render(<Activity events={history}/>))
 const list=container.querySelector('[aria-label="Recent remediation activity"]')
 expect(list.tabIndex).toBe(0)
 expect(list.children).toHaveLength(25)
 expect(list.textContent).toContain('Saved document 24')
 expect(readFileSync('src/remediation-ops-panel.css','utf8')).toMatch(/\.remops-history-scroll>ol\{[^}]*height:420px;overflow-y:scroll;[^}]*scrollbar-gutter:stable/)
})
