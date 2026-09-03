import { scanCriteria, scanDocTypes } from './frozenScope.js'
import { scopeSentence } from './scanScope.js'
import { deriveLevel } from './AssessSetup.jsx'
import AccordionSection from './AccordionSection.jsx'

// "Scope of this assertion" (approved board 7) — what the numbers above are a claim ABOUT.
//
// The Overview exports as the compliance report, and a compliance report that states findings
// without stating its own boundary is the document this panel exists to prevent. Every row here
// answers a question an auditor asks first: which files, which document types, which criteria,
// what was deliberately left out.
//
// THREE RULES, and they are the same three the rest of this redesign runs on.
//
//   1. Read from the RUN, never from the live setting. `run.scan_scope` is frozen at scan start
//      (R6 / Phase 3a), so an operator who widened the global scope afterwards still sees what
//      THIS run covered. Re-describing a past run with today's settings is the drift that made
//      "1 file then 8 files" unexplainable.
//   2. A row with no answer does not render. Not "—", not "all", not "none" — absent. `null`
//      scan_scope means UNRESTRICTED, which is a fact and is stated as one; a row we genuinely
//      cannot fill is simply not there, because an auditor reading a blank field will supply
//      their own assumption and it will be the generous one.
//   3. No score, and no sentence shaped like one. Board 7's footer read "A score of 100 would
//      mean no blocking findings among the criteria evaluated". #545 removed the score, so the
//      caveat is rewritten to make the same point without resurrecting it: the assertion covers
//      the criteria that were EVALUATED, which is not the same as conformance.

const row = { display: 'flex', gap: 14, alignItems: 'flex-start', padding: '9px 0',
              borderTop: '1px solid var(--line)' }
const label = { width: 150, flex: '0 0 150px', fontSize: 12.5, color: 'var(--muted)' }
const value = { flex: 1, minWidth: 0, fontSize: 13.5, lineHeight: 1.5 }

const Row = ({ name, children }) => (
  <div style={row}>
    <div style={label}>{name}</div>
    <div style={value}>{children}</div>
  </div>
)

const FORMAT_LABEL = { docx: 'DOCX', pdf: 'PDF', pptx: 'PPTX', xlsx: 'XLSX', html: 'HTML' }

/**
 * @param run       the scan run. `scan_scope` is the frozen criterion→formats map (or null).
 * @param fileCount documents in this run, for the source sentence's denominator.
 * @param coreScs   the document-core criteria set, backing the "null means the whole core" reading.
 * @param rec       reconcileBuckets(...) output, for the exclusion row. Omitted → no exclusion row.
 */
export default function AssertionScope({ run, fileCount = 0, coreScs, rec = null }) {
  if (!run) return null

  const scanScope = run.scan_scope
  const criteria = scanCriteria(scanScope, coreScs)
  const types = scanDocTypes(scanScope)
  const core = (coreScs && coreScs.size) || 0
  // Derived from the criteria that ran, never picked. Null when there is nothing to derive it
  // from — a conformance target is not something to default.
  const level = deriveLevel([...criteria])

  const source = scopeSentence(run.scope, fileCount)
  const lifecycle = rec ? rec.rows.find((r) => r.key === 'lifecycle') : null
  const heldBack = lifecycle && lifecycle.measured ? lifecycle.value : null
  const overridden = rec ? rec.overridden : null

  // Approved-by is deliberately absent. The discovery acknowledgement is captured on the Discover
  // tab but is not projected onto the run, so this screen has no attributable approver or time to
  // print. Rendering the row empty would read as "nobody approved"; inventing the signed-in user
  // would attribute an approval they may not have given. It renders only if the run ever carries
  // one, and until then the panel says nothing about approval at all.
  const approver = run.approved_by || null
  const approvedAt = run.approved_at || null

  return (
    <AccordionSection id="assertion-scope" title="Scope of this Assertion"
                      ariaLabel="Scope of this assertion" defaultOpen={false}>

      {source && <Row name="Source">{source}</Row>}

      <Row name="Document types">
        {types && types.length
          ? types.map((t) => FORMAT_LABEL[t] || t.toUpperCase()).join(', ')
          : <>All supported document types <span className="muted">— this run was not narrowed by type</span></>}
      </Row>

      <Row name="Criteria">
        {criteria.size
          ? <>{criteria.size}{core ? ` of the Core ${core}` : ''}
              {level && <> · <b>WCAG 2.1 {level}</b> <span className="muted">— derived from the criteria selected, not chosen separately</span></>}</>
          : <span className="muted">Not recorded for this run</span>}
      </Row>

      {/* Only when the partition actually measured it. "0 excluded" from an unmeasured bucket is
          the same false reassurance as a score over an unassessed estate. */}
      {heldBack != null && (
        <Row name="Exclusion policy">
          {heldBack.toLocaleString()} {heldBack === 1 ? 'file' : 'files'} held back by a lifecycle
          recommendation
          {overridden != null && overridden > 0 && <> · {overridden.toLocaleString()} individually overridden and assessed</>}
          <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>
            Held back means not assessed. Nothing was archived, moved or deleted.
          </div>
        </Row>
      )}

      {approver && (
        <Row name="Approved by">{approver}{approvedAt ? ` · ${approvedAt}` : ''}</Row>
      )}

      {/* The caveat that stops this panel being read as a conformance certificate. Deliberately
          NOT phrased around a score — that verdict was removed in #545 and must not return here
          in a sentence. */}
      <p className="muted" style={{ fontSize: 12, margin: '12px 0 0', lineHeight: 1.55 }}>
        These findings describe <b>the criteria that were evaluated, on the documents that were
        assessed</b>. That is not the same as conformance: a criterion nobody could test is neither
        a pass nor a failure, and this assertion says nothing about it.
      </p>
    </AccordionSection>
  )
}
