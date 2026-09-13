import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join, dirname } from 'node:path'
import { priorStageResults, guardStageAction } from './priorStageResults.js'
import Discover from './Discover.jsx'
import Remediate from './Remediate.jsx'
import AssessSummary from './AssessSummary.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

vi.mock('./api.js', async (actual) => ({...(await actual()), getScanInventory:vi.fn(async()=>({total:1,rows:[{file:'result.docx',mime:'application/vnd.openxmlformats-officedocument.wordprocessingml.document',status:'discovered',lifecycle_status:'Archive Candidate',lifecycle_rule_id:'fixture-rule'}]}))}))
const stages = ['discover', 'assess', 'remediate', 'release']
const lineage = (last, scanId = 'scan') => ({scan_id:scanId,workflow_revision:2,
 stages:stages.slice(0,stages.indexOf(last)+1).map(stage=>({stage,workflow_revision:2,revision:1,state:'succeeded'}))})
afterEach(unmountAll)

it.each(stages)('keeps only %s and downstream stage actions available', (last) => {
 const result=priorStageResults(lineage(last),'scan')
 stages.forEach((stage,index)=>expect(result[stage]).toBe(index<stages.indexOf(last)))
})
it('ignores another scan, stale workflow revision, and resets for a new scan',()=>{
 expect(priorStageResults(lineage('release'),'new-scan').assess).toBe(false)
 const old=lineage('release');old.stages.forEach(stage=>stage.workflow_revision=1)
 expect(priorStageResults(old,'scan').discover).toBe(false)
 expect(priorStageResults(lineage('discover','new-scan'),'new-scan').discover).toBe(false)
})
it('blocks events captured before advancement while current-stage retries stay available',()=>{
 const ref={current:{...priorStageResults(lineage('assess'),'scan'),scanId:'scan'}};const call=vi.fn()
 const assess=guardStageAction(ref,'assess',call)
 assess();expect(call).toHaveBeenCalledTimes(1)
 ref.current={...priorStageResults(lineage('remediate'),'scan'),scanId:'scan'};assess()
 expect(call).toHaveBeenCalledTimes(1)
 ref.current={...priorStageResults(lineage('discover','new'),'new'),scanId:'new'};assess()
 expect(call).toHaveBeenCalledTimes(1)
 guardStageAction(ref,'assess',call)();expect(call).toHaveBeenCalledTimes(2)
})
it('renders real Discover inventory without advance or scope repeat actions after advancement', async()=>{
 const {container,root}=createTestRoot();const advance=vi.fn();const scan=vi.fn()
 const props={sources:[],files:[{file:'result.docx',type:'DOCX',status:'done',issues:[]}],
  scanId:'scan',run:{id:'scan',status:'done',completed_at:'2026-09-13'},onAdvance:advance,onScan:scan,
  showRunProgress:false,resultsOnly:false}
 await act(async()=>root.render(createElement(Discover,props)))
 expect(container.querySelector('[data-advance="assess"]')).toBeTruthy()
 await act(async()=>root.render(createElement(Discover,{...props,resultsOnly:true})))
 expect(container.querySelector('[data-advance="assess"]')).toBeNull()
 expect(container.textContent).toContain('result.docx')
 expect(advance).not.toHaveBeenCalled();expect(scan).not.toHaveBeenCalled()
 // Back-navigation does not change the durable results-only flag.
 await act(async()=>root.render(createElement(Discover,{...props,resultsOnly:true})))
 expect(container.querySelector('[data-advance="assess"]')).toBeNull()
 await act(async()=>root.render(createElement(Discover,{...props,scanId:'new-scan',run:{...props.run,id:'new-scan'},resultsOnly:priorStageResults(lineage('discover','new-scan'),'new-scan').discover})))
 expect(container.querySelector('[data-advance="assess"]')).toBeTruthy()
})
it('renders real Remediate results with no start action once Release started',()=>{
 history.replaceState({},'','/?tab=remediate')
 const html=renderToStaticMarkup(createElement(Remediate,{run:{id:'scan',status:'done'},files:[],resultsOnly:true}))
 const c=document.createElement('div');c.innerHTML=html
 expect(c.textContent).toContain('Remediation')
 expect([...c.querySelectorAll('button')].filter(b=>!b.hidden&&/Start remediation|Approve all|Apply all/.test(b.textContent))).toHaveLength(0)
 expect(c.querySelector('[role="tablist"]')).toBeTruthy()
})
it('wires durable flags to actual App actions and prevents stale start/bulk callbacks',()=>{
 const app=readFileSync(join(dirname(fileURLToPath(import.meta.url)),'App.jsx'),'utf8')
 expect(app).toContain('priorStageResults(canonicalRun.lineage, scan?.run?.id,')
 expect(app).toContain('if (priorResultsRef.current.assess) return')
 expect(app).toContain('!rows?.length || priorResultsRef.current.assess')
 expect(app).toContain('resultsOnly={priorResults.discover || isTimeTravel}')
 expect(app).toContain('resultsOnly={priorResults.remediate}')
 expect(app).toContain('!priorResults.assess && !(busy')
 expect(app).toContain('onBulkFix={priorResults.assess ? undefined')
 expect(app).toContain("assessPhase === 'done' || (priorResults.assess && assessed)")
 expect(app).toContain("!priorResults[view === 'publish' ? 'release' : view]")
})

it.each(stages)('keeps saved Assess results browseable at durable %s with only valid stage advance actions', async(last)=>{
 const {container,root}=createTestRoot();const flags=priorStageResults(lineage(last),'scan');const action=vi.fn();const details=vi.fn()
 await act(async()=>root.render(createElement(AssessSummary,{files:[{file:'result.docx',status:'analysed',issues:[{wcag:'SC_1_1_1',severity:'SERIOUS'}]}],
  cap:{docx:{'1.1.1':'assisted'}},assessment:{docx:{'1.1.1':'review'}},criteria:new Set(['1.1.1']),
  onRemediate:flags.assess?undefined:action,onRunDetails:details})))
 const start=[...container.querySelectorAll('button')].find(b=>/Start remediation/.test(b.textContent))
 expect(Boolean(start)).toBe(!flags.assess)
 if(start)await act(async()=>start.click())
 expect(action).toHaveBeenCalledTimes(flags.assess?0:1)
 const browse=[...container.querySelectorAll('button')].find(b=>/Run details/.test(b.textContent))
 expect(browse).toBeTruthy();await act(async()=>browse.click());expect(details).toHaveBeenCalledOnce()
})

it('holds existing-scan mutations until durable lineage arrives, while initial discovery stays available',()=>{
 const ref={current:{...priorStageResults(null,'saved',{awaitingLineage:true}),scanId:'saved'}};const action=vi.fn()
 const click=guardStageAction(ref,'assess',action);click();expect(action).not.toHaveBeenCalled()
 ref.current={...priorStageResults(lineage('remediate','saved'),'saved'),scanId:'saved'};click();expect(action).not.toHaveBeenCalled()
 expect(priorStageResults(null,'new',{awaitingLineage:false}).discover).toBe(false)
})

it('keeps Undo out of historical remediation detail panes', () => {
 const source=readFileSync(join(dirname(fileURLToPath(import.meta.url)),'Remediate.jsx'),'utf8')
 expect(source).toContain('!reviewReadOnly && sel.autoApplied && !sel.inspectionOnly')
})
