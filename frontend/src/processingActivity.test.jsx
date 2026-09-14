import { act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import AssessRunProgress from './AssessRunProgress.jsx'
import { RemediationActivityPanel } from './RemediationOpsPanel.jsx'
import { titleCaseStep } from './processingActivity.js'
afterEach(unmountAll)
it('title cases action language while preserving acronyms', () => {
  expect(titleCaseStep('checking WCAG contrast with AI')).toBe('Checking WCAG Contrast With AI')
})
it('rejects remediation actions in the mounted Assess row', () => {
  const html = renderToStaticMarkup(<AssessRunProgress snapshot={{available:true,active:true,phase:'assessing', totals:{eligible:10}, kpis:{completed:2,processing:1}, queue:{phase:'remediating',current:{file:'Exact File.docx',action:'describing image 1 of 1'},in_flight:1}}} />)
  expect(html).not.toContain('describing image')
  expect(html).not.toContain('Exact File.docx')
})
it('shows actual remediation steps and unchanged filename in the mounted Live panel', async () => {
  const {root,container}=createTestRoot()
  const props={snapshot:{batch_id:'b',scan_id:'s',state:'processing'},activity:{stage:'remediate',phase:'remediating',file:'exact-UPPER file.docx',action:'describing image 1 of 1',at:Date.now()/1000}}
  await act(async()=>root.render(<RemediationActivityPanel {...props} />))
  expect(container.textContent).toContain('Processing Now: exact-UPPER file.docx · Generating Alt Text For Image 1 Of 1')
  await act(async()=>root.render(<RemediationActivityPanel {...props} activity={{...props.activity,stage:'assess',phase:'analysing',action:'checking contrast'}} />))
  expect(container.textContent).not.toContain('Processing Now:')
  await act(async()=>root.render(<RemediationActivityPanel {...props} activity={{...props.activity,at:Date.now()/1000-121}} />))
  expect(container.textContent).not.toContain('Processing Now:')
  await act(async()=>root.render(<RemediationActivityPanel {...props} snapshot={{...props.snapshot,terminal:true}} />))
  expect(container.textContent).not.toContain('Processing Now:')
})

it('title cases the mounted Assess action and leaves the file path unchanged', () => {
  const html = renderToStaticMarkup(<AssessRunProgress snapshot={{available:true,active:true,phase:'assessing', totals:{eligible:10}, kpis:{completed:2,processing:1}, queue:{phase:'analysing',current:{file:'exact-UPPER file.docx',action:'checking non-text content for WCAG'},in_flight:1}}} />)
  expect(html).toContain('Processing Now:')
  expect(html).toContain('exact-UPPER file.docx')
  expect(html).toContain('Checking Non-Text Content For WCAG')
})
