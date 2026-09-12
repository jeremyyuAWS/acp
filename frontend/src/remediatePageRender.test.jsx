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
it('puts workspace tabs first and current activity at the start of the default Live panel', () => {
 history.replaceState({}, '', '/?tab=remediate')
 const container = document.createElement('div')
 container.innerHTML = renderToString(<Remediate run={{ id: 'current', status: 'completed' }} files={[]}
   runStream={{ snapshot: { scan_id: 'current', run_id: 'current', batch_id: 'batch', state: 'processing', terminal: false }, events: [{key:'saved',file:'file.pdf',line:'Saved corrected copy',tone:'success'}], connected: true, receivedAt: Date.now() }} />)
 expect(container.firstElementChild.getAttribute('role')).toBe('tablist')
 const live = container.querySelector('#rem-panel-live')
 expect(live.hidden).toBe(false)
 expect(live.children[1].getAttribute('aria-label')).toBe('Remediation live activity')
 expect(live.querySelectorAll('[aria-label="Remediation live activity"]')).toHaveLength(1)
 expect(live.textContent).toContain('Saved corrected copy')
 expect(live.querySelector('[aria-label="Remediation run"]')).toBeNull()
 expect(live.querySelector('#accepted-run-details').tagName).toBe('DETAILS')
 expect(live.querySelector('#accepted-run-details').open).toBe(false)
 expect(container.querySelector('#rem-panel-review').hidden).toBe(true)
 expect(container.querySelector('#rem-panel-waterfall').hidden).toBe(true)
})

it('retains the summary card before remediation starts', () => {
 history.replaceState({}, '', '/?tab=remediate')
 const container = document.createElement('div')
 container.innerHTML = renderToString(<Remediate run={{id:'not-started',status:'completed'}} files={[]} />)
 expect(container.querySelector('[aria-label="Remediation run"]')).toBeTruthy()
})
