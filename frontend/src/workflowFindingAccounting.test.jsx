import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import Card from './WorkflowStageActivityCard.jsx'
it('names accounted findings and the missing outcome instead of claiming fix completion', () => {
  const html = renderToStaticMarkup(<Card snapshot={{ stage: 'remediate', state: 'processing_complete',
    reconciliation: {total:2,accounted:2,exact:true}, integrity:{ok:false},
    domain_reconciliation:{unit:'assessed findings',total:8,accounted:7,exact:false,
      buckets:{resolved_verified:4,awaiting_review:3}} }} />)
  expect(html).toContain('assessed findings accounted for')
  expect(html).toContain('1 assessed finding still lack a recorded outcome')
  expect(html).toContain('88% accounted for')
  expect(html).not.toContain('88% complete')
})
