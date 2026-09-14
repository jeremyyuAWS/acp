import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import React from 'react'
import Card from './RemediationRunCard.jsx'
import { counterRows, secondaryRows } from './remediationSnapshot.js'
const snapshot = { state: 'running', total_documents: 147, documents: { completed: 0, processing: 20, waiting: 53, review: 10, skipped: 64, failed: 0 }, fixes: { applied: 1381, verified: 1381, documents_verified: 80 }, delivery: { awaiting_release: 86 } }
it('uses the detailed view document buckets and metric units for the same snapshot', () => {
  const html = renderToStaticMarkup(<Card snapshot={snapshot} />)
  for (const row of counterRows(snapshot).filter(row => row.value > 0)) {
    expect(html).toContain(`${row.value.toLocaleString()}</b> ${row.label.toLowerCase()}`)
  }
  expect(html).not.toContain('74</b> blocked')
  for (const row of secondaryRows(snapshot)) expect(html).toContain(row.label)
  expect(html).toContain('>74</span>')
  expect(html).toContain('of 147 documents through automatic processing')
})
it('does not show a fabricated queue progress total when partition counters disagree', () => {
  const html = renderToStaticMarkup(<Card snapshot={{ ...snapshot, documents: { ...snapshot.documents, waiting: 0 } }} />)
  expect(html).not.toContain('documents through automatic processing')
  expect(html).toContain('These counters do not add up')
})
