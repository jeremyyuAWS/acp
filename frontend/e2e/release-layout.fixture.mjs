// Run from frontend: node e2e/release-layout.fixture.mjs
// Isolated Vite fixture; all API imports are mocked and nonlocal requests are blocked.
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { chromium, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
const api = readFileSync('src/api.js', 'utf8')
const names = [...api.matchAll(/export\s+(?:async\s+)?(?:const|function)\s+(\w+)/g)].map(m => m[1])
const fixtures = {
 getReleaseContinuation: null, planReleaseContinuation: { id:'exact-fixture-plan', status:'draft', intent:{ files:{ 'Eligible proposal.pptx':{rows:[{id:'proposal-v1',rule_id:'1.1.1',authorize:true,proposals:[{proposed_value:'A chart of quarterly revenue.'}]}],blockers:[]}, 'Unknown readiness.docx':{rows:[],blockers:['Manual repair required']} } } },
 getSettings: { drive_mirror_enabled: false }, getSourceStatus: { files: [], stale_count: 0 }, listHitlQueue: [],
 getReleaseStatus: { release_id: 'fixture-receipt', roots: [{ folder_id: 'fixture', folder_name: 'September delivery', folder_url: 'https://example.test/folder' }], documents: [{ file: 'Delivered annual report.pdf', status: 'published', published_at: '2026-09-02' }, { file: 'Needs another attempt.pdf', status: 'failed', explanation: 'Destination permissions changed. Restore access and retry.' }] },
 listReleaseHistory: { releases: [] }, getReleaseAiProvenance: { calls: [] },
 previewReleaseDestination: { can_release: true, folder_name: 'September delivery', documents: [{file: 'Ready corrected policy.pdf', destination_path: 'Remediated / September delivery / Ready corrected policy.pdf'}] },
}
fixtures.authorizeReleaseContinuation = {...fixtures.planReleaseContinuation, status:'waiting', progress:{'Eligible proposal.pptx':{state:'applying',message:'Applying the authorized proposal'}}}
const app = `import React from 'react'; import {createRoot} from 'react-dom/client'; import Publish from '/src/Publish.jsx'; import Access from '/src/RemediationReleaseAccess.jsx'; import '/src/styles.css';
const verified=(file,extra={})=>({file,compliant:1,remediated_at:'2026-09-01',corrected_sha256:'fixture-digest',score:100,...extra});
createRoot(document.getElementById('root')).render(<main style={{maxWidth:1100,margin:'auto',padding:16}}>{!location.search.includes('zero') && <Access files={[verified('Ready corrected policy.pdf'),{file:'Still processing.docx',status:'running'}]} onNavigate={()=>{globalThis.__releaseNavigation='publish'}} />}<Publish run={{status:'running',id:'isolated-release-fixture',source:'local',files:5}} files={location.search.includes('zero') ? [{file:'Unknown readiness.docx'}] : [verified('Ready corrected policy.pdf'),verified('Delivered annual report.pdf'),verified('Needs another attempt.pdf'),{file:'Unknown readiness.docx'},verified('Eligible proposal.pptx',{compliant:0})]} /></main>);`
const server = await createServer({ configFile:false, root:process.cwd(), plugins:[{name:'isolated-release-fixture', enforce:'pre', resolveId(id){if(id==='./api.js'||id.endsWith('/src/api.js'))return '\0fixture-api'; if(id==='/fixture.jsx')return process.cwd()+'/fixture.jsx'}, load(id){if(id==='\0fixture-api')return names.map(n=>`export const ${n}=async(...args)=>{(globalThis.__releaseCalls??=[]).push([${JSON.stringify(n)},args]);return (${n==='planReleaseContinuation' ? `location.search.includes('zero') ? {id:'zero-plan',intent:{files:{}}} : ` : n==='getReleaseStatus' ? `location.search.includes('zero') ? {documents:[]} : ` : ''}${ JSON.stringify(Object.hasOwn(fixtures,n)?fixtures[n]:{})});}`).join('\n'); if(id===process.cwd()+'/fixture.jsx')return app},configureServer(s){s.middlewares.use(async (req,res,next)=>{if(req.url.startsWith('/release-fixture')){res.setHeader('Content-Type','text/html');res.end(await s.transformIndexHtml('/release-fixture','<html><head><title>Isolated Release fixture</title></head><body><div id="root"></div><script type="module" src="/fixture.jsx"></script></body></html>'))}else next()})}},react()],server:{host:'127.0.0.1',port:5190,strictPort:true} })
await server.listen()
const browser = await chromium.launch({channel:'chrome',headless:true})
try {
 const page = await browser.newPage({reducedMotion:'reduce'})
 const errors=[]; page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/*',route=>route.request().url().startsWith('http://127.0.0.1:5190') ? route.continue() : route.abort())
 await page.goto('http://127.0.0.1:5190/release-fixture'); await page.getByRole('heading',{name:'Release',exact:true}).waitFor()
 for(const width of [1280,390,320]){
  await page.setViewportSize({width,height:900})
  await expect(page.getByRole('button',{name:'Open Release · 1 verified copy',exact:true})).toBeVisible()
  await page.getByRole('button',{name:'Publish ready files (1)',exact:true}).waitFor({timeout:5000}).catch(async error=>{console.log(await page.locator('body').innerText()); console.log(errors); throw error})
  await page.getByRole('button',{name:'Approve eligible changes and publish when ready',exact:true}).waitFor()
  if(await page.locator('.release-advanced').getAttribute('open') !== null) throw Error('Advanced details should start collapsed')
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)
  if(overflow)throw Error(`Horizontal overflow at ${width}`)
  await page.getByRole('button',{name:'Publish ready files (1)',exact:true}).scrollIntoViewIfNeeded()
  await page.screenshot({path:`/tmp/release-quick-${width}.png`,fullPage:true})
 }
 await page.getByRole('button',{name:'Approve eligible changes and publish when ready',exact:true}).click()
 const calls = await page.evaluate(()=>globalThis.__releaseCalls)
 const approvals = calls.filter(([name])=>name==='authorizeReleaseContinuation')
 if(approvals.length!==1 || approvals[0][1][1]!=='exact-fixture-plan') throw Error('Approval must bind exactly one server plan')
 if(calls.some(([name])=>name==='publishAllFiles')) throw Error('Approving must not bypass verification with a client publish')
 await page.goto('http://127.0.0.1:5190/release-fixture?zero');
 for(const width of [1280,390,320]){
  await page.setViewportSize({width,height:900})
  const ready = page.getByRole('button',{name:'Publish ready files (0)',exact:true})
  const approve = page.getByRole('button',{name:'Approve eligible changes and publish when ready',exact:true})
  await ready.waitFor(); await approve.waitFor()
  if(!await ready.isDisabled() || !await approve.isDisabled())throw Error('Zero-ready actions must remain disabled')
  await page.getByText('No complete, versioned proposals are ready for this action.',{exact:false}).waitFor()
  if(await page.locator('.release-quick').evaluate(el=>Boolean(el.closest('details'))))throw Error('Primary actions hidden in disclosure')
  if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth))throw Error(`Zero-ready overflow at ${width}`)
  await page.screenshot({path:`/tmp/release-visible-zero-${width}.png`,fullPage:true})
 }
 if(errors.length)throw Error(errors.join('\n'))
 console.log('Isolated current-worktree fixture passed at 1280, 390 and 320px, reduced motion; no horizontal overflow or page errors. Screenshots: /tmp/release-quick-{width}.png')
} finally { await browser.close(); await server.close() }
