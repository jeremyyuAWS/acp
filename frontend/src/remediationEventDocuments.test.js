import { describe, expect, it } from 'vitest'
import { addRemediationEvent, documentHistories, eventDocumentKey,
         remediationEventLine } from './remediationEventFeed.js'

// The client half of ADR 0052. The server now names the document in its own field, correlates
// events to a batch, says whether an event is material, and — where the run's privacy policy
// requires it — withholds the name while keeping a per-run identity. Each of those is a claim
// about what the browser must NOT invent.

describe('the document a remediation event belongs to', () => {
  it('reads the structured field the server now sends', () => {
    expect(remediationEventLine({ kind: 'remediate.delivered', document: 'Board Pack.pdf' }))
      .toMatch(/Board Pack\.pdf/)
  })

  it('still reads events written before the column existed', () => {
    // The log is DURABLE: rows written the old way are replayed on every resume. Dropping this
    // fallback would blank the names in exactly the history a reconnecting client came back for.
    expect(remediationEventLine({ kind: 'remediate.delivered', detail: { file: 'Legacy.docx' } }))
      .toMatch(/Legacy\.docx/)
  })

  it('says "a document" when the server suppressed the name, rather than implying it is unknown', () => {
    // Suppression is a decision the server made. "Document" would read as ACP not knowing which
    // one; the line has to say that a specific document is meant and its name is withheld.
    const line = remediationEventLine({
      kind: 'remediate.verified', document: null, document_suppressed: true, detail: { fixes: 2 },
    })
    expect(line).toMatch(/verified for a document/)
  })

  it('never invents a name from anything else on the event', () => {
    const line = remediationEventLine({
      kind: 'remediate.delivered', detail: { destination: 'SharePoint/HR/Policies' },
    })
    expect(line).not.toMatch(/SharePoint/)
  })
})

describe('parallel documents keep independent ordered histories', () => {
  const feed = () => {
    // Interleaved, and deliberately NOT in seq order — a resumed client receives replayed history
    // after live frames it already had, so arrival order is not the document's order.
    const arrivals = [
      [{ kind: 'remediate.verified', document_ref: 'aaa', document: 'A.pdf' }, 5],
      [{ kind: 'remediate.fix_applied', document_ref: 'bbb', document: 'B.docx' }, 2],
      [{ kind: 'remediate.fix_applied', document_ref: 'aaa', document: 'A.pdf' }, 1],
      [{ kind: 'remediate.delivered', document_ref: 'bbb', document: 'B.docx' }, 4],
      [{ kind: 'remediate.delivered', document_ref: 'aaa', document: 'A.pdf' }, 7],
    ]
    let rows = []
    for (const [event, id] of arrivals) rows = addRemediationEvent(rows, event, id)
    return rows
  }

  it('groups by document and orders each history by the durable seq, not by arrival', () => {
    const histories = documentHistories(feed())
    expect([...histories.keys()].sort()).toEqual(['aaa', 'bbb'])
    expect(histories.get('aaa').map((row) => row.id)).toEqual(['1', '5', '7'])
    expect(histories.get('bbb').map((row) => row.id)).toEqual(['2', '4'])
  })

  it('keeps grouping working when the names are suppressed', () => {
    // The ref is what survives suppression, which is the entire reason it exists.
    let rows = []
    rows = addRemediationEvent(rows, {
      kind: 'remediate.fix_applied', document_ref: 'ref-1', document_suppressed: true }, 1)
    rows = addRemediationEvent(rows, {
      kind: 'remediate.verified', document_ref: 'ref-1', document_suppressed: true }, 2)
    rows = addRemediationEvent(rows, {
      kind: 'remediate.fix_applied', document_ref: 'ref-2', document_suppressed: true }, 3)
    const histories = documentHistories(rows)
    expect(histories.get('ref-1')).toHaveLength(2)
    expect(histories.get('ref-2')).toHaveLength(1)
  })

  it('drops rows it cannot attribute rather than pooling them under one fake document', () => {
    // A run-level event (`remediate.accepted`) belongs to no document. Bundling those together
    // would render a phantom document whose history is every un-attributed line in the run.
    const rows = addRemediationEvent([], { kind: 'remediate.accepted', detail: { documents: 3 } }, 1)
    expect(rows).toHaveLength(1)
    expect(eventDocumentKey(rows[0])).toBe(null)
    expect(documentHistories(rows).size).toBe(0)
  })
})

describe('material progress is the server’s judgement, not the browser’s', () => {
  it('carries the flag through untouched', () => {
    const [row] = addRemediationEvent([], {
      kind: 'remediate.fix_applied', document: 'A.pdf', material: true }, 1)
    expect(row.material).toBe(true)
  })

  it('records an absent flag as unknown, never as false', () => {
    // An older server, or a row replayed from before the classification existed. `false` would
    // assert the event was mere lease activity; unknown asserts nothing.
    const [row] = addRemediationEvent([], { kind: 'remediate.fix_applied', document: 'A.pdf' }, 1)
    expect(row.material).toBe(null)
  })

  it('carries attempt, phase and correlation so a card can say which try it is on', () => {
    const [row] = addRemediationEvent([], {
      kind: 'remediate.fix_applied', document: 'A.pdf', attempt: 2, phase: 'applying',
      correlation_id: 'batch-9', material: true }, 4)
    expect(row.attempt).toBe(2)
    expect(row.phase).toBe('applying')
    expect(row.correlationId).toBe('batch-9')
  })

  it('leaves a missing attempt as unknown rather than reporting attempt zero', () => {
    const [row] = addRemediationEvent([], { kind: 'remediate.delivered', document: 'A.pdf' }, 1)
    expect(row.attempt).toBe(null)
  })
})
