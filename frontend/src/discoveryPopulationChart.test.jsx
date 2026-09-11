import {it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import Chart from './DiscoveryPopulationChart.jsx'
it('includes excluded source files and reconciles every slice to the source denominator',()=>{
 const html=renderToStaticMarkup(<Chart inventory={{discovered:7101,by_status:{assessable:986,metadata_only:44,unsupported:5886,excluded:185}}} />)
 expect(html).toContain('986 + 44 + 5,886 + 185 = 7,101 source files')
 expect(html).toContain('Excluded: 185')
 expect(html).toContain('13.9%')
})
it('keeps uncategorized files visible and refuses overcounts',()=>{
 expect(renderToStaticMarkup(<Chart inventory={{discovered:10,by_status:{assessable:8}}} />)).toContain('Not classified: 2')
 expect(renderToStaticMarkup(<Chart inventory={{discovered:1,by_status:{excluded:2}}} />)).not.toContain('<svg')
})
