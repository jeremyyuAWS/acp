import {it,expect} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import Stack from './WorkflowStageStack.jsx'

it('shows the source exclusions and complete inventory partition under the completed Discover step',()=>{
  const props={lineage:{scan_id:'same',workflow_revision:1,stages:[{stage:'discover',state:'succeeded',workflow_revision:1,
    domain_reconciliation:{total:6916,partitioned:6916,buckets:{active:6916},exact:true}}]},
    discoveryScope:{scanId:'same',scope:{kind:'drive',inventory:{discovered:7101,assessment_eligible:986,
      by_status:{excluded:185,metadata_only:44,unsupported:5886}}}}}
  const html=renderToStaticMarkup(<Stack {...props} />)
  expect(html).toContain('6,916 inventoried + 185 excluded = 7,101 found')
  expect(html).toContain('986 + 44 + 5,886 = 6,916 inventoried files')
  expect(html).toContain('185 ACP-generated files excluded from rescanning')
  expect(renderToStaticMarkup(<Stack {...props} discoveryScope={{...props.discoveryScope,scanId:'other'}} />)).not.toContain('7,101')
})
