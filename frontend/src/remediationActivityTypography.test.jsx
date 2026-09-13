import { act } from 'react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { createTestRoot, unmountAll } from './testRoots.js'
import { Activity, RemediationActivityPanel } from './RemediationOpsPanel.jsx'
let previousActEnvironment
beforeEach(()=>{previousActEnvironment=globalThis.IS_REACT_ACT_ENVIRONMENT;globalThis.IS_REACT_ACT_ENVIRONMENT=true})
afterEach(async()=>{await unmountAll();globalThis.IS_REACT_ACT_ENVIRONMENT=previousActEnvironment})
const name='Very_long_document_name_with_no_spaces_and_a_repeated_identifier_123456789012345678901234567890.docx'
const events=[{key:'latest',documentKey:'doc',tone:'success',occurredAt:'2026-09-13T12:00:00Z',line:`2 fixes independently verified for ${name}`},
  {key:'previous',documentKey:'doc',tone:'attention',occurredAt:'2026-09-13T12:00:00Z',line:`Corrected copy of ${name} saved in ACP · source delivery is unavailable`}]
it('uses the same shared mono entry selectors for standalone and run activity with preserved document history', async () => {
  const {root,container}=createTestRoot()
  await act(async()=>root.render(<><Activity events={events}/><RemediationActivityPanel snapshot={{scan_id:'scan',batch_id:'batch',state:'processing'}} events={events}/></>))
  const feeds=container.querySelectorAll('.remops-activity')
  expect(feeds).toHaveLength(2)
  for (const feed of feeds) {
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
