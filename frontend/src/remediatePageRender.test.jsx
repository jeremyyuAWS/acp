import { describe, it, expect } from 'vitest'
import { renderToString } from 'react-dom/server'
import Remediate from './Remediate.jsx'

// Exercise the real page composition: a JSX prop referenced a variable that did
// not exist, so even Plan crashed before its child components could render.
describe('Remediate page composition', () => {
  it.each(['plan', 'live', 'review'])('renders the %s URL with an assessed scan', (mode) => {
    history.replaceState({}, '', `/?tab=remediate&mode=${mode}`)
    const html = renderToString(<Remediate run={{ id: 'assessed-scan', status: 'completed' }}
      files={[]} runStream={{ snapshot: { run_id: 'assessed-scan', total_documents: 4 }, events: [] }} />)
    expect(html).toContain('Remediation')
  })
})
