// Run from frontend: node e2e/release-layout.fixture.mjs
// Isolated Vite fixture; all API imports are mocked and nonlocal requests are blocked.
import { createServer } from 'vite'
import react from '@vitejs/plugin-react'
import { chromium } from '@playwright/test'
import { readFileSync } from 'node:fs'
const api = readFileSync('src/api.js', 'utf8')
const names = [...api.matchAll(/export\s+(?:async\s+)?(?:const|function)\s+(\w+)/g)].map(m => m[1])
const fixtures = {
 getSettings: { drive_mirror_enabled: false }, getSourceStatus: { files: [], stale_count: 0 }, listHitlQueue: [],
 getReleaseStatus: { release_id: 'fixture-receipt', roots: [{ folder_id: 'fixture', folder_name: 'September delivery', folder_url: 'https://example.test/folder' }], documents: [{ file: 'Delivered annual report.pdf', status: 'published', published_at: '2026-09-02' }, { file: 'Needs another attempt.pdf', status: 'failed', explanation: 'Destination permissions changed. Restore access and retry.' }] },
 listReleaseHistory: { releases: [] }, getReleaseAiProvenance: { calls: [] },
 previewReleaseDestination: { can_release: true, folder_name: 'September delivery', documents: [{file: 'Ready corrected policy.pdf', destination_path: 'Remediated / September delivery / Ready corrected policy.pdf'}] },
}
const app = `import React from 'react'; import {createRoot} from 'react-dom/client'; import Publish from '/src/Publish.jsx'; import '/src/styles.css';
const verified=(file,extra={})=>({file,compliant:1,remediated_at:'2026-09-01',score:100,...extra});
createRoot(document.getElementById('root')).render(<main style={{maxWidth:1100,margin:'auto',padding:16}}><Publish run={{id:'isolated-release-fixture',source:'local',files:5}} files={[verified('Ready corrected policy.pdf'),verified('Delivered annual report.pdf'),verified('Needs another attempt.pdf'),{file:'Unknown readiness.docx'},verified('Awaiting correction.pptx',{remediated_at:null})]} /></main>);`
const server = await createServer({ configFile:false, root:process.cwd(), plugins:[{name:'isolated-release-fixture', enforce:'pre', resolveId(id){if(id==='./api.js'||id.endsWith('/src/api.js'))return '\0fixture-api'; if(id==='/fixture.jsx')return process.cwd()+'/fixture.jsx'}, load(id){if(id==='\0fixture-api')return names.map(n=>`export const ${n}=async()=>(${JSON.stringify(fixtures[n] ?? {})});`).join('\n'); if(id===process.cwd()+'/fixture.jsx')return app},configureServer(s){s.middlewares.use(async (req,res,next)=>{if(req.url==='/release-fixture'){res.setHeader('Content-Type','text/html');res.end(await s.transformIndexHtml('/release-fixture','<html><head><title>Isolated Release fixture</title></head><body><div id="root"></div><script type="module" src="/fixture.jsx"></script></body></html>'))}else next()})}},react()],server:{host:'127.0.0.1',port:5190,strictPort:true} })
await server.listen()
const browser = await chromium.launch({channel:'chrome',headless:true})
try {
 const page = await browser.newPage({reducedMotion:'reduce'})
 const errors=[]; page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/*',route=>route.request().url().startsWith('http://127.0.0.1:5190') ? route.continue() : route.abort())
 await page.goto('http://127.0.0.1:5190/release-fixture'); await page.getByRole('heading',{name:'Release',exact:true}).waitFor()
 for(const width of [1280,390,320]){
  await page.setViewportSize({width,height:900})
  await page.getByRole('button',{name:'Choose delivery',exact:true}).click()
  await page.getByRole('button',{name:'Review release',exact:true}).click()
  await page.getByRole('button',{name:'Publish 2 copies',exact:true}).waitFor({timeout:3000})
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)
  if(overflow)throw Error(`Horizontal overflow at ${width}`)
  await page.getByRole('button',{name:'Publish 2 copies',exact:true}).scrollIntoViewIfNeeded()
  await page.screenshot({path:`/tmp/release-${width}.png`,fullPage:true})
  await page.getByRole('button',{name:'Back to delivery',exact:true}).click()
  await page.getByRole('button',{name:'Back to files',exact:true}).click()
 }
 if(errors.length)throw Error(errors.join('\n'))
 console.log('Isolated current-worktree fixture passed at 1280, 390 and 320px, reduced motion; no horizontal overflow or page errors. Screenshots: /tmp/release-{width}.png')
} finally { await browser.close(); await server.close() }
