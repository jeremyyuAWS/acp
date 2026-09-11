import { describe, it, expect } from 'vitest'
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import AssessmentEvidenceDetails from './AssessmentEvidenceDetails.jsx'
import AssessRunProgress from './AssessRunProgress.jsx'

const scope = { scan_scope: { '2.4.6': ['docx'], '1.1.1': ['pdf'], '1.4.3': [] } }
it('shows saved selected criterion numbers and names only', () => {
  const html = renderToStaticMarkup(createElement(AssessmentEvidenceDetails, { scope }))
  expect(html).toContain('SC 1.1.1 — Non-text Content')
  expect(html).toContain('SC 2.4.6 — Headings and Labels')
  expect(html).not.toContain('SC 1.4.3')
})
it('distinguishes observed responses from unsuccessful or blocked telemetry', () => {
  const html = renderToStaticMarkup(createElement(AssessmentEvidenceDetails, { scope, activity: {
    available: true, records: 4, groups: [{zone:'cloud',provider:'ollama',model:'llava',records:4,succeeded:1}],
    reasons:[{reason:'circuit_open',records:3}],
  } }))
  expect(html).toContain('1 successful responses; 3 unsuccessful or blocked records')
  expect(html).toContain('Provider temporarily paused after repeated failures')
  expect(html).toContain('ollama')
})
it('gives completed assessment details real expandable content', async () => {
  const host = document.createElement('div'); document.body.appendChild(host)
  const root = createRoot(host)
  await act(async () => root.render(createElement(AssessRunProgress, { snapshot: {
    available:true,phase:'done',totals:{eligible:1},kpis:{completed:1},scope,
  } })))
  const details = host.querySelector('details.assess-live-details')
  expect(details.open).toBe(false)
  await act(async () => details.querySelector('summary').click())
  expect(details.open).toBe(true)
  expect(details.textContent).toContain('SC 1.1.1 — Non-text Content')
  await act(async () => details.querySelector('summary').click())
  expect(details.open).toBe(false)
  await act(async () => root.unmount()); host.remove()
})
