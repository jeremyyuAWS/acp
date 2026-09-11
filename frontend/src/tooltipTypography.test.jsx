import {act} from 'react'
import {afterEach,it,expect} from 'vitest'
import {readFileSync} from 'node:fs'
import {dirname,join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {createTestRoot,unmountAll} from './testRoots.js'
import Term from './Term.jsx'
import InfoTip from './InfoTip.jsx'
import RemediationOptionHelp from './RemediationOptionHelp.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)),'tooltip-typography.css'),'utf8')
afterEach(unmountAll)
for (const [name,component] of [
 ['glossary',<Term k="assessment_waiting">Waiting</Term>],
 ['info',<InfoTip label="findings"><b>Findings</b><span>ACP records WCAG findings.</span></InfoTip>],
 ['remediation',<RemediationOptionHelp label="tools"><b>Tools</b><span>ACP records WCAG findings.</span></RemediationOptionHelp>],
]) {
 it(`keeps ${name} tooltip headings and text in authored case inside uppercase KPI labels`,async()=>{
  const {root,container}=createTestRoot()
  await act(async()=>root.render(<><style>{css}</style><dl><dt style={{textTransform:'uppercase',letterSpacing:'.04em'}}>{component}</dt></dl></>))
  await act(async()=>container.querySelector('button').focus())
  const tooltip=container.querySelector('[role="tooltip"]')
  expect(tooltip).not.toBeNull()
  for(const node of [tooltip,...tooltip.querySelectorAll('*')]) {
    expect(getComputedStyle(node).textTransform).toBe('none')
    expect(getComputedStyle(node).letterSpacing).toBe('normal')
  }
  expect(getComputedStyle(container.querySelector('dt')).textTransform).toBe('uppercase')
  expect(tooltip.textContent).toContain(name==='glossary' ? 'Eligible documents' : 'ACP records WCAG findings.')
 })
}
