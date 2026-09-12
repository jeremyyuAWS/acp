// Isolated real-component/CSS audit. Run from frontend: node e2e/app-styling.fixture.mjs
// No API or credentials; the Vite root is this owned worktree, never the shared preview.
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { chromium, expect } from '@playwright/test'

const entry = `import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
import Summary from '/src/RemediationProgressSummary.jsx';import Outcomes from '/src/WorkflowOutcomeTiles.jsx';import Drawer from '/src/ProgressQueueDrawer.jsx';
import '/src/styles.css';import '/src/site-picker.css';import '/src/release-file-selection.css';import '/src/remediation-live-documents.css';import '/src/document-findings-table.css';
const name='ReferralLetter_'+ 'VeryLongUnbrokenDocumentName'.repeat(12)+'.docx';
function Fixture(){const [open,setOpen]=useState(false);const [count,setCount]=useState(123456);return <main className="app">
<nav className="tabs" aria-label="Workflow">{['Sources','Discover','Assess','Remediate','Release','Live Operations','Scan Analytics','Knowledge Graph','Conformance'].map(x=><button key={x}>{x}</button>)}</nav>
<section className="sp-picker"><div className="sp-picker__actions"><button>New folder</button><button>Select this folder</button><span>Current folder selection</span></div></section>
<Summary documents={[{progressState:'ready'}]} onSelect={()=>setOpen(true)} queueMode/>
<Outcomes stage="remediate" domain={{total:count,buckets:{resolved_verified:count}}} onFilter={()=>setOpen(true)}/>
<section className="remediation-live-documents"><div className="live-document-categories live-finding-filters"><button className="live-finding-filter live-finding-filter--all" aria-pressed="true">All findings</button><button className="live-finding-filter">Verified <strong>123456</strong></button></div>
<div className="document-findings-scroll document-findings-scroll-all" tabIndex="0"><table className="document-findings-table live-document-table"><thead><tr><th scope="col">Document</th><th scope="col" className="findings-criteria-heading">WCAG criteria<br/>with issues</th><th scope="col" className="findings-total-heading">Total<br/>findings</th><th scope="col">Remediation categories</th></tr></thead><tbody>{Array.from({length:25},(_,i)=><tr key={i}><th scope="row" className="fname">{name}</th><td>6</td><td>123456</td><td>Verified</td></tr>)}</tbody></table></div></section>
<section className="release-selection__drawer"><dl><dt>VeryLongUnbrokenMetadataLabel</dt><dd>{name}</dd></dl></section>
<button id="update" onClick={()=>setCount(x=>x+100000)}>Update confirmed count</button><button id="open" onClick={()=>setOpen(true)}>Open queue fixture</button>
{open&&<Drawer title="Files needing attention" files={[{file:name,status:'unknown',label:'Awaiting confirmed assessment and destination readiness',reason:name}]} onClose={()=>setOpen(false)}/>}</main>};createRoot(document.getElementById('root')).render(<Fixture/>);`
const server = await createServer({configFile:false,root:process.cwd(),plugins:[react(),{
 name:'styling-audit',resolveId(id){if(id==='/styling-fixture.jsx'||id===process.cwd()+'/styling-fixture.jsx')return process.cwd()+'/styling-fixture.jsx'},
 load(id){if(id===process.cwd()+'/styling-fixture.jsx')return entry},
 configureServer(server){server.middlewares.use(async(req,res,next)=>{if(req.url==='/styling-audit'){res.setHeader('Content-Type','text/html');res.end(await server.transformIndexHtml('/styling-audit','<html><div id="root"></div><script type="module" src="/styling-fixture.jsx"></script></html>'))}else next()})}
}],server:{host:'127.0.0.1',port:0}})
await server.listen()
const browser=await chromium.launch({headless:true,...(process.env.ACP_E2E_CHROMIUM?{executablePath:process.env.ACP_E2E_CHROMIUM}:{})})
try {
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',message=>{if(message.type()==='error')errors.push(message.text())})
 await page.route('**/*',route=>route.request().url().startsWith('http://127.0.0.1:')?route.continue():route.abort())
 for(const width of [1280,640,390,320]) {
  await page.setViewportSize({width,height:900});await page.goto(`http://127.0.0.1:${server.httpServer.address().port}/styling-audit`)
  await page.locator('#open').waitFor()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width)
  for(const selector of ['.workflow-outcome-tiles__tile','.sp-picker__actions','.release-selection__drawer']) {
   expect(await page.locator(selector).evaluateAll(nodes=>nodes.every(el=>el.scrollWidth<=el.clientWidth+1)),`${selector} clips at ${width}`).toBe(true)
  }
  await page.locator('#update').click();await expect(page.locator('.workflow-outcome-tiles__tile .kpi-update-delta')).toHaveText('+100,000')
  expect(await page.locator('.workflow-outcome-tiles__tile').evaluateAll(nodes=>nodes.every(el=>el.scrollWidth<=el.clientWidth+1)),`Animated delta clips at ${width}`).toBe(true)
  const table=page.locator('.document-findings-scroll');await table.evaluate(el=>{el.scrollTop=150;el.scrollLeft=100})
  expect(await page.locator('thead').evaluate(el=>getComputedStyle(el).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)')
  expect(await page.locator('.fname').first().evaluate(el=>getComputedStyle(el).fontFamily)).toBe(await page.locator('th[scope="col"]').first().evaluate(el=>getComputedStyle(el).fontFamily))
  await page.locator('#open').click();await expect(page.getByRole('dialog')).toBeVisible()
  expect(await page.locator('.progress-queue-file').evaluate(el=>el.scrollWidth<=el.clientWidth),`Drawer content overflow at ${width}`).toBe(true)
  await expect(page.getByRole('button',{name:'Close queue'})).toBeFocused()
  await page.keyboard.press('Shift+Tab');await expect(page.getByLabel('Queue files')).toBeFocused()
  await page.keyboard.press('Tab');await expect(page.getByRole('button',{name:'Close queue'})).toBeFocused()
  await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.locator('#open')).toBeFocused()
  await page.emulateMedia({reducedMotion:'reduce'});await page.locator('#open').click()
  expect(await page.getByRole('dialog').evaluate(el=>getComputedStyle(el).animationName)).toBe('none')
  await page.screenshot({path:`/tmp/acp-styling-audit-${width}.png`,fullPage:true});await page.keyboard.press('Escape')
 }
 expect(errors).toEqual([])
 console.log('Real component/CSS audit passed at 1280, 640 (200% effective width), 390 and 320px; long names, large counts, sticky headers, keyboard/focus, reduced motion. Screenshots /tmp/acp-styling-audit-{width}.png')
} finally {await browser.close();await server.close()}
