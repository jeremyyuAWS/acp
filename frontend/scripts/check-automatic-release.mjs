import { createServer } from 'vite'
import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
const server=await createServer({root:new URL('../',import.meta.url).pathname,server:{host:'127.0.0.1',port:0}})
await server.listen()
const origin=new URL(server.resolvedUrls.local[0]).origin
const browser=await chromium.launch({headless:true})
try {
for(const width of [1280,390]){
 const page=await browser.newPage({viewport:{width,height:700},reducedMotion:'reduce'})
 await page.route('**/*',route=>{assert.equal(route.request().method(),'GET');assert.equal(new URL(route.request().url()).origin,origin);return route.continue()})
 await page.goto(origin+'/fixtures/automatic-release.html')
 const checkbox=page.getByRole('checkbox',{name:'Automatically release files when ready'})
 await checkbox.waitFor()
 assert.equal(await checkbox.isChecked(),false)
 assert.equal(await page.evaluate(()=>window.fixtureReleaseActions.length),0)
 await checkbox.check()
 await page.getByRole('button',{name:'Stop future releases'}).waitFor()
 assert.equal(await checkbox.isChecked(),true)
 assert.equal(await page.evaluate(()=>window.fixtureReleaseActions[0].intent.run_id),'fixture-execution')
 await page.screenshot({path:`/tmp/acp-automatic-release-${width}.png`})
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
 await page.getByRole('button',{name:'Stop future releases'}).click()
 await page.getByText('Future releases stopped. Files already delivered remain available.').waitFor()
 assert.deepEqual(await page.evaluate(()=>window.fixtureReleaseActions.map(a=>a.action)),['enable','stop'])
 await page.close()
}
console.log('Desktop/mobile explicit opt-in, destination, progress, stop, and no network writes passed.')
}finally{await browser.close();await server.close()}
