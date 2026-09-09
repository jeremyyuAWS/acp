import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { chromium, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
const source = readFileSync('src/remediationOpsPanel.test.jsx','utf8')
const snapshot = source.slice(source.indexOf('const SNAP = '), source.indexOf('\n\nconst render ='))
const names = [...readFileSync('src/api.js','utf8').matchAll(/export\s+(?:async\s+)?(?:const|function)\s+(\w+)/g)].map(m=>m[1])
const app = `import React from 'react';import {createRoot} from 'react-dom/client';import Panel from '/src/RemediationOpsPanel.jsx';import '/src/styles.css';
${snapshot}
const saved = location.search.includes('saved');
const exceptions={view:{groups:[{key:'authoring_required',label:'Needs authoring',documents:5,items:Array.from({length:5},(_,i)=>({file:('LongDocumentNameWithoutSpaces'.repeat(12))+i+'.docx',reason:'Manual authoring required',action_enabled:false}))}],controls:[]},error:false,reload:()=>{}};
createRoot(document.getElementById('root')).render(<main style={{maxWidth:1100,margin:'auto',padding:12}}><Panel snapshot={{...SNAP,terminal:true,state:'processing_complete'}} exceptions={exceptions} activityStatus="ready" events={saved?[{key:'7',id:'7',line:'A corrected document was verified',occurredAt:'2026-09-09T12:00:00Z',tone:'success'}]:[]} /></main>);`
const server=await createServer({configFile:false,root:process.cwd(),plugins:[{name:'fixture',enforce:'pre',resolveId(id){if(id==='./api.js'||id.endsWith('/src/api.js'))return '\0fixture-api';if(id==='/activity-fixture.jsx')return process.cwd()+'/activity-fixture.jsx'},load(id){if(id==='\0fixture-api')return names.map(n=>`export const ${n}=async()=>({available:false,groups:[],controls:[]});`).join('\n');if(id===process.cwd()+'/activity-fixture.jsx')return app},configureServer(s){s.middlewares.use(async(req,res,next)=>{if(req.url.startsWith('/activity-fixture?')){res.setHeader('Content-Type','text/html');res.end(await s.transformIndexHtml(req.url,'<div id="root"></div><script type="module" src="/activity-fixture.jsx"></script>'))}else next()})}},react()],server:{host:'127.0.0.1',port:5191,strictPort:true}})
await server.listen();const browser=await chromium.launch({channel:'chrome',headless:true})
try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',route=>route.request().url().startsWith('http://127.0.0.1:5191')?route.continue():route.abort())
 for(const state of ['empty','saved'])for(const width of [1280,768,390,320]){
  await page.setViewportSize({width,height:900});await page.goto(`http://127.0.0.1:5191/activity-fixture?${state}`)
  const area=page.locator('.remops-bottom');await expect(area).toBeVisible()
  if(width<=760)await area.locator('summary').first().click()
  if(state==='empty'){await expect(area).toContainText('No recent remediation activity is recorded for this run.');expect(await page.locator('.remops-activity').evaluate(e=>e.getBoundingClientRect().height)).toBeLessThan(150)}else await expect(area).toContainText('A corrected document was verified')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false)
  await expect(page.getByText('Where your findings stand')).toHaveCount(0)
  await expect(page.getByText('Finding outcome totals unavailable · why?')).toHaveCount(0)
  await area.screenshot({path:`/tmp/activity-${state}-${width}.png`})
 }
 if(errors.length)throw Error(errors.join('\n'));console.log('Saved and empty activity passed with long filenames at 1280/768/390/320px; no overflow or page errors.')
}finally{await browser.close();await server.close()}
