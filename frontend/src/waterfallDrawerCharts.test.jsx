import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Charts, { ContributionBars, ProcessingPace, ActivityTrend, SettledSpend } from './WaterfallDrawerCharts.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
async function render(element) { const v = createTestRoot(); await act(async () => v.root.render(element)); return v.container }
it('keeps unavailable data compact and limits overview to three modules', async () => { const c = await render(<Charts />); expect(c.querySelectorAll('section')).toHaveLength(3); expect(c.querySelector('svg')).toBeNull() })
it('exposes exact units and native-button drilldown', async () => {
 const inspect=vi.fn(); const c=await render(<ContributionBars data={{unit:'Validated attempts',basis:'Recorded validation',rows:[{id:'usable',label:'Usable output',value:3},{id:'missing',label:'Missing',value:null}]}} onInspect={inspect}/>);
 expect(c.querySelectorAll('button')).toHaveLength(1); expect(c.textContent).toContain('Validated attempts'); await act(async()=>c.querySelector('button').click()); expect(inspect).toHaveBeenCalledWith('usable')
})
it('requires a disclosed scale for gauges and a full observation window for pace', async()=>{
 const data={value:4,unit:'Recorded completions/min',observedSeconds:60,windowLabel:'Last 60 seconds'};
 const c=await render(<ProcessingPace data={data}/>); expect(c.querySelector('svg')).toBeNull(); expect(c.textContent).toContain('4');
 const gauge=await render(<ProcessingPace data={{...data,scaleMax:10,scaleLabel:'Configured capacity'}}/>); expect(gauge.querySelector('svg').getAttribute('aria-label')).toContain('Configured capacity');
 const short=await render(<ProcessingPace data={{...data,observedSeconds:20}}/>); expect(short.textContent).toContain('Collecting pace data')
})
it('preserves missing observations as line gaps and accessible table values',async()=>{
 const c=await render(<ActivityTrend data={{unit:'Recorded completions/min',timeZone:'UTC',bucketLabel:'60-second buckets',windowLabel:'Recorded run',points:[{timestamp:'2026-09-09T10:00:00Z',value:2},{timestamp:'2026-09-09T10:01:00Z',value:null},{timestamp:'2026-09-09T10:02:00Z',value:3}]}}/>);
 expect(c.querySelectorAll('path')[1].getAttribute('d').match(/M/g)).toHaveLength(2); expect(c.querySelector('table').textContent).toContain('Unavailable'); expect(c.querySelectorAll('tbody tr')).toHaveLength(3)
})
it.each([[false,true,3,false],[true,false,3,false],[true,true,4,false],[true,true,3,true]])('draws donuts only for a complete reconciled partition (%s,%s,%s)',async(complete,partition,total,draw)=>{
 const c=await render(<SettledSpend data={{complete,partition,total,unit:'USD',rows:[{id:'a',label:'Model A',value:1},{id:'b',label:'Model B',value:2}]}}/>);
 expect(Boolean(c.querySelector('svg'))).toBe(draw); expect(c.textContent).toContain('$1.00'); expect(c.textContent).toContain('Reserved spending is separate'); if(!draw)expect(c.textContent).not.toContain('%')
})
it('uses a list for zero or single-category cost and bounds composition to six slices',async()=>{
 const c=await render(<SettledSpend data={{complete:true,partition:true,total:0,unit:'USD',rows:[{id:'a',label:'A',value:0}]}}/>); expect(c.querySelector('svg')).toBeNull(); expect(c.textContent).toContain('$0.00');
 const rows=Array.from({length:8},(_,i)=>({id:String(i),label:`Model ${i}`,value:1})); const d=await render(<SettledSpend data={{complete:true,partition:true,total:8,unit:'USD',rows}}/>); expect(d.querySelectorAll('circle')).toHaveLength(6); expect(d.textContent).toContain('Other')
})
