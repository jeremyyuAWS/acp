import { documentRow, findingsByCriterion, SEVERITIES, SEVERITY_LABEL } from './assessMetrics.js'
import { criterionOf } from './wcagFinding.js'
import { RULE_DETAILS } from './ruleDetails.js'

// Level 3 of the drill-down: ONE document's findings, grouped by WCAG success criterion.
//
// Summary (the estate) → file worklist (which documents) → this (what is wrong inside one of them).
//
// WHY THE GROUPING LIVES INSIDE A FILE AND NEVER ABOVE IT. Remediation happens to documents: you
// open the file, you fix things, you save it. A rule-first worklist — "1.1.1 across the estate, 40
// findings" — reads efficient and is the opposite, because it asks one person to open the same
// board pack five times, once per criterion. So the top-level list is documents (level 2) and the
// criterion grouping is what happens once you are already inside one. Within a file the grouping
// earns its place: it tells the fixer what KIND of work the next twenty minutes is, which is the
// question "11 findings" cannot answer.
//
// NOTHING IS DRAFTED, APPROVED OR APPLIED HERE. Assessment answers "does this document have alt
// text, a header row, a title". It does not produce the replacement — generating alt text is a
// vision-model call that lives in the remediation path, not in a detector. So this screen carries
// no proposed alt text, no suggested title, no "Approve" and no "Apply". Every fixMode line is a
// statement about WHERE AND HOW the work happens later, never an offer to do it now. A drafts-at-
// assess screen would have implied the assessment stage calls the model, which it does not.
//
// ORDER IS THE MODULE'S, NOT OURS. `findingsByCriterion` sorts groups by what needs a PERSON first,
// then worst severity, then criterion number — so a group of auto-fixable CRITICAL findings sorts
// BELOW a group of MINOR findings that need somebody. That is deliberate: after remediation runs
// the first group is gone and the second still needs a human, and human attention is the scarce
// resource. This component therefore contains NO sort of its own. It splits the list at the
// needsPerson boundary with a slice — which cannot reorder — and labels the two bands, because an
// ordering rule nobody has been told is invisible.
//
// DE-EMPHASIS IS NOT A FILTER. The deprioritised band still renders every group with its real
// severity, its real count and every one of its findings. The failure mode of a "these matter less"
// rule is that it quietly becomes a hidden set, so nothing here hides anything — and there are no
// sort or filter controls, which would let a reader reorder the one ordering that carries meaning.

const SEV_COLOR = { CRITICAL: '#8E1B14', SERIOUS: '#B3261E', MODERATE: '#B07A00', MINOR: '#B9B3BE',
                    UNKNOWN: '#9A93A0' }
const SEV_TAG_BG = { CRITICAL: '#F6E2E0', SERIOUS: '#FDEDEC', MODERATE: '#FFF6E3', MINOR: '#F2F0F4',
                     UNKNOWN: '#F2F0F4' }
const SEV_TAG_FG = { CRITICAL: '#8E1B14', SERIOUS: '#B3261E', MODERATE: '#B07A00',
                     MINOR: 'var(--muted)', UNKNOWN: 'var(--muted)' }

const kicker = { fontSize: 11.5, letterSpacing: '.07em', textTransform: 'uppercase',
                 color: 'var(--muted)', fontWeight: 600 }
const mono = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }
const bigNum = { fontSize: 22, fontWeight: 700, marginTop: 3, fontVariantNumeric: 'tabular-nums' }

// The three fix modes, and the only three sentences this screen says about them.
//
// `auto` means DETERMINISTIC — same input, same output, no model call. An AI-drafted fix is not
// auto: it is advice a person still has to accept, and counting it as automation is what produced
// "51% auto-remediable" for work nobody could apply unattended. All three sentences name
// remediation as the place the work happens, because none of it happens here.
const FIX_MODE_ROW = {
  auto: 'Fixed automatically in remediation',
  assisted: 'AI drafts it in remediation, you approve it there',
  human: 'You author it in remediation',
}
// The same three facts as a count, for a group header. Written per mode so a mixed group can list
// them side by side rather than collapsing to "some auto, some not".
const FIX_MODE_GROUP = {
  auto: (n) => `${n} fixed automatically`,
  assisted: (n) => `${n} AI-drafted for your approval`,
  human: (n) => `${n} you author`,
}
const FIX_MODE_ONLY = {
  auto: (n) => `ACP fixes ${n === 1 ? 'this one' : `these ${n}`} automatically in remediation`,
  assisted: (n) => `AI drafts ${n === 1 ? 'a fix' : `${n} fixes`} in remediation, you approve ${n === 1 ? 'it' : 'them'} there`,
  human: (n) => `You author ${n === 1 ? 'this fix' : `these ${n} fixes`} in remediation`,
}
const MODES = ['auto', 'assisted', 'human']

// A finding's fixMode comes from assessMetrics (capability.modeFor); anything it could not place is
// treated as 'human', which is capability.js's own conservative default and never a silent 'auto'.
const modeOf = (x) => (MODES.includes(x.fixMode) ? x.fixMode : 'human')

// Tally the three modes over a group's findings. This counts a field assessMetrics already decided
// per finding — it does not re-derive fixability, and there is no fourth bucket to disagree about.
function modeTally(findings) {
  const t = { auto: 0, assisted: 0, human: 0 }
  for (const x of findings) t[modeOf(x)]++
  return t
}

// What kind of work this criterion is, in one clause. One mode present ⇒ one sentence; more than
// one ⇒ the counts listed, so "2 findings · 1 auto-fixable" can never hide that the other needs a
// person. Never a button: this sentence is where the work happens, not an offer to do it.
function workSentence(findings) {
  const t = modeTally(findings)
  const present = MODES.filter((m) => t[m] > 0)
  if (present.length === 1) return FIX_MODE_ONLY[present[0]](t[present[0]])
  return `${present.map((m) => FIX_MODE_GROUP[m](t[m])).join(', ')} — all in remediation`
}

// Where the finding is. The analysers attribute a 1-based page/slide (issue_records.page); a
// finding they could not place carries none and gets NO location rather than a wrong one. xlsx
// findings locate by cell, not page, so having none is correct rather than missing.
function locationOf(x, fmt) {
  const page = Number(x.page)
  if (!Number.isFinite(page) || page <= 0) return null
  return `${fmt === 'pptx' ? 'Slide' : 'Page'} ${page}`
}

// What the engine saw, in the words maintained beside the detector. `detail` when the finding
// carries one, else the rule's own title from the generated rule catalogue, else the criterion's
// name. Deliberately NOT `fix`, `impact`, or any proposal/draft field: this row says what is wrong
// and where, and stops.
function describe(x, sc) {
  if (x.detail) return String(x.detail)
  const rule = RULE_DETAILS[x.rule_id] || RULE_DETAILS[x.ruleId]
  if (rule && rule.title) return rule.title
  return criterionOf(sc)?.name || sc
}

function SevDot({ severity }) {
  return <span aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, display: 'inline-block',
                                           background: SEV_COLOR[severity] || SEV_COLOR.UNKNOWN }} />
}

function SevTag({ severity }) {
  const label = SEVERITY_LABEL[severity] || 'unclassified'
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600,
                   padding: '2px 9px', borderRadius: 20, whiteSpace: 'nowrap',
                   background: SEV_TAG_BG[severity] || SEV_TAG_BG.UNKNOWN,
                   color: SEV_TAG_FG[severity] || SEV_TAG_FG.UNKNOWN }}>
      <SevDot severity={severity} />{label.charAt(0).toUpperCase() + label.slice(1)}
    </span>
  )
}

function Group({ group, fmt }) {
  const c = criterionOf(group.sc)
  const level = group.level || c?.level
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 12, marginTop: 10, overflow: 'hidden',
                  background: 'var(--surface)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 15px',
                    borderBottom: '1px solid var(--line)', flexWrap: 'wrap' }}>
        <SevTag severity={group.severity} />
        <div style={{ minWidth: 180 }}>
          <div style={{ fontSize: 13.5, fontWeight: 650 }}>
            {group.sc}{c ? ` ${c.name}` : ''}
            {level && <span className="muted" style={{ fontWeight: 400 }}> · Level {level}</span>}
          </div>
          {/* The criterion's requirement, from the maintained catalogue rather than written here —
              so the sentence a reader checks the finding against is the same one everywhere. */}
          {c?.req && <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>{c.req}</div>}
        </div>
        <div className="muted" style={{ marginLeft: 'auto', fontSize: 12, textAlign: 'right' }}>
          <b>{group.findings.length}</b> finding{group.findings.length === 1 ? '' : 's'}
          {' · '}{workSentence(group.findings)}
        </div>
      </div>

      {group.findings.map((x, i) => {
        const where = locationOf(x, fmt)
        return (
          <div key={`${x.rule_id || x.ruleId || group.sc}-${i}`}
               style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '11px 15px',
                        fontSize: 12.5, borderTop: i === 0 ? 'none' : '1px solid var(--line)',
                        flexWrap: 'wrap' }}>
            {where && <span className="muted" style={{ ...mono, fontSize: 11.5, whiteSpace: 'nowrap' }}>{where}</span>}
            <span style={{ flex: '1 1 240px' }}>{describe(x, group.sc)}</span>
            {/* A statement, never a control. Nothing on this screen applies or approves a fix. */}
            <span className="muted" style={{ fontSize: 11.5, whiteSpace: 'nowrap' }}>
              {FIX_MODE_ROW[modeOf(x)]}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function Band({ title, note, groups, fmt }) {
  if (!groups.length) return null
  return (
    <div style={{ marginTop: 16 }}>
      <div style={kicker}>{title}</div>
      <p className="muted" style={{ fontSize: 12, margin: '4px 0 0', lineHeight: 1.6 }}>{note}</p>
      {groups.map((g) => <Group key={g.sc} group={g} fmt={fmt} />)}
    </div>
  )
}

/**
 * One document's findings.
 *
 * @param row   a `documentRow` from assessMetrics — the same per-file pass the summary and the
 *              worklist read, handed down rather than recomputed so the three views cannot
 *              disagree about how many findings this file has.
 * @param file  the raw file row, used ONLY when `row` is absent (this component then asks
 *              assessMetrics for it) and for file metadata the metrics module does not carry.
 * @param cap / assessment / criteria / level — passed through to `documentRow` when computing.
 * @param onBack / onNext / nextName  navigation back to the worklist and on to the next document.
 * @param onRemediate  the one action: hand this document to remediation. No fix is applied here.
 */
export default function AssessFileFindings({ row, file, cap, assessment, criteria, level = 'AA',
                                             assessedAt, onBack, onNext, nextName, onRemediate }) {
  const r = row || documentRow(file, { cap, assessment, criteria, level })

  // Nothing, rather than zeros. A document that was never opened produced no verdict — it is not a
  // document with no findings, and "0 findings · 0 auto-fixable" over a file ACP could not read is
  // the single most misleading thing this screen could print. `findingsByCriterion` returns null on
  // exactly the same condition, which is the check being made here.
  const groups = findingsByCriterion(r)
  if (!r || !groups) return null

  // NO SORT. `findingsByCriterion` already ordered these by what needs a person, then severity,
  // then criterion number. The two bands are a SLICE at the boundary — an operation that cannot
  // reorder — so the labels describe the module's order rather than imposing one of their own.
  const boundary = groups.findIndex((g) => !g.needsPerson)
  const needsPerson = boundary === -1 ? groups : groups.slice(0, boundary)
  const deterministic = boundary === -1 ? [] : groups.slice(boundary)

  // Passed = criteria evaluated for this document that produced no finding. Both sets come from
  // assessMetrics; the difference is a presentation of them, not a second count of the findings.
  const failing = new Set(r.criteriaFailing)
  const passed = r.criteriaEvaluated.filter((sc) => !failing.has(sc))
  const noMethod = r.unassessableCriteria
  const identityHolds = failing.size + passed.length + noMethod.length === r.selectedChecks
  const FMT = (r.fmt || '').toUpperCase()
  // A13 board fields — file size and a Drive link. Both come from the RAW file record (`file`),
  // never from the derived row, which carries neither. Rendered only when the field is actually
  // present: a "0 KB" or a dead link invented from nothing is worse than the field being absent.
  const sizeKB = file?.sizeKB ?? file?.size_kb
  const sizeLabel = sizeKB ? (sizeKB >= 1024 ? `${(sizeKB / 1024).toFixed(1)} MB` : `${sizeKB} KB`) : null
  const driveUrl = file?.drive_file_id
    ? `https://drive.google.com/file/d/${encodeURIComponent(file.drive_file_id)}/view` : null

  return (
    <section className="assessfilefindings">

      {(onBack || onNext) && (
        <div className="muted" style={{ fontSize: 12.5 }}>
          {onBack && <button className="linklike" type="button" onClick={() => onBack()}>← All documents</button>}
          {onNext && (
            <button className="linklike" type="button" style={{ marginLeft: 12 }} onClick={() => onNext()}>
              next{nextName ? `: ${nextName}` : ''} →
            </button>
          )}
        </div>
      )}

      {/* ── The file, and the numbers that tie to its row in the worklist ─────────────────── */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
                    gap: 16, marginTop: 10, flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ ...mono, margin: 0, fontSize: 17, fontWeight: 650 }}>{r.name}</h2>
          <div className="muted" style={{ marginTop: 5, fontSize: 12.5 }}>
            {/* Every segment renders only when the file actually carries it — never a "0 pages" or
                "assessed —" for a value nobody sent. sizeLabel and assessedAt both arrive pre-derived
                (KB→MB done here from the raw record; the timestamp pre-formatted by the caller, the
                same fmtStamp contract every other stamp on this screen uses). */}
            {FMT && <>{FMT} · </>}
            {sizeLabel && <>{sizeLabel} · </>}
            {file?.pages ? <>{file.pages} pages · </> : null}
            {file?.sheets ? <>{file.sheets} sheets · </> : null}
            {assessedAt && <>assessed {assessedAt} · </>}
            WCAG 2.1 Level {level}
          </div>
        </div>
        <span style={{ display: 'flex', gap: 8 }}>
          {driveUrl && (
            // `.ghost`/`.small` are button-only selectors (styles.css:68/156) and do not style an
            // <a>, so the equivalent chrome is inlined rather than applying classes that would
            // silently do nothing on this element.
            <a href={driveUrl} target="_blank" rel="noopener noreferrer"
               style={{ display: 'inline-flex', alignItems: 'center', fontSize: 13, padding: '6px 12px',
                        borderRadius: 9, background: '#fff', color: 'var(--plum)',
                        border: '1px solid var(--line)', textDecoration: 'none' }}>
              Open in Drive
            </a>
          )}
          {onRemediate && r.totalFindings > 0 && (
            <button type="button" onClick={() => onRemediate(r)}>Send to remediation</button>
          )}
        </span>
      </div>

      <div className="panel" style={{ marginTop: 14, display: 'flex', gap: 40, alignItems: 'center',
                                      flexWrap: 'wrap' }}>
        <div>
          <div style={kicker}>Findings</div>
          <div style={bigNum}>{r.totalFindings}</div>
        </div>
        <div>
          <div style={kicker}>Severity</div>
          <div style={{ marginTop: 6, fontSize: 12, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {SEVERITIES.map((s) => (
              <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 4,
                                     fontVariantNumeric: 'tabular-nums' }}>
                <SevDot severity={s} /><b>{r.bySeverity[s]}</b> {SEVERITY_LABEL[s]}
              </span>
            ))}
            {/* Never dropped: a severity that vanished would break the printed sum silently. */}
            {r.bySeverity.UNKNOWN > 0 && <span><b>{r.bySeverity.UNKNOWN}</b> unclassified</span>}
          </div>
        </div>
        <div>
          <div style={kicker}>Auto-fix available</div>
          <div style={{ ...bigNum, color: '#2F7D32' }}>{r.autoFixAvailable}</div>
        </div>
        <div>
          <div style={kicker}>Human review required</div>
          <div style={bigNum}>{r.humanReviewRequired}</div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div style={kicker}>Coverage for this file</div>
          <div style={{ fontSize: 13, marginTop: 5 }}>
            {r.criteriaEvaluated.length} of {r.selectedChecks} criteria evaluated
          </div>
          {noMethod.length > 0 && (
            <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
              {noMethod.length} {noMethod.length === 1 ? 'has' : 'have'} no method for {FMT || 'this format'}
            </div>
          )}
        </div>
      </div>

      {/* ── Level 3 · the grouping, and what it is for ────────────────────────────────────── */}
      <div style={{ marginTop: 20 }}>
        <span style={{ fontSize: 15, fontWeight: 650 }}>Findings by WCAG success criterion</span>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {' '}— {failing.size} criteri{failing.size === 1 ? 'on' : 'a'} failing,
          {' '}{r.totalFindings} finding{r.totalFindings === 1 ? '' : 's'}
        </span>
      </div>
      <p className="muted" style={{ fontSize: 12, margin: '9px 0 0', lineHeight: 1.6 }}>
        This screen reports what was found. Nothing is drafted, approved or applied here — every
        fix, including AI-drafted alt text, happens in remediation. Each group says which kind of
        fix it will get there.
      </p>

      <Band
        title="Needs a person"
        note={'Somebody has to decide or author these. They come first because a person’s attention '
              + 'is the scarce thing here — the groups below cost nobody an afternoon.'}
        groups={needsPerson}
        fmt={r.fmt}
      />
      <Band
        title="ACP fixes these in remediation"
        note={'Deterministic: same input, same output, no model call and no judgement. Listed after '
              + 'the work above because remediation clears them, not because they are less severe — '
              + 'each group keeps its own severity and every finding is listed.'}
        groups={deterministic}
        fmt={r.fmt}
      />

      {/* ── What passed, and what could not be assessed. Kept out of the worklist above, and
             kept ON the page: a criterion with no method is neither a pass nor a failure, and a
             screen that showed only failures would let it be read as a pass by omission. ────── */}
      <div className="panel" style={{ marginTop: 18 }}>
        <div style={{ display: 'flex', gap: 40, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 260px' }}>
            <div style={{ ...kicker, color: '#2F7D32' }}>
              {passed.length} criteri{passed.length === 1 ? 'on' : 'a'} passed
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 7, lineHeight: 1.7 }}>
              {passed.length ? passed.join(' · ') : 'None — every criterion evaluated for this document produced a finding.'}
            </div>
          </div>
          <div style={{ flex: '1 1 260px' }}>
            <div style={kicker}>
              {noMethod.length} criteri{noMethod.length === 1 ? 'on' : 'a'} could not be assessed
            </div>
            <div className="muted" style={{ fontSize: 12.5, marginTop: 7, lineHeight: 1.7 }}>
              {noMethod.length
                ? <>
                    {noMethod.map((sc) => `${sc}${criterionOf(sc) ? ` ${criterionOf(sc).name}` : ''}`).join(' · ')}
                    <br />
                    <b style={{ color: 'var(--ink)' }}>
                      ACP has no method for {noMethod.length === 1 ? 'this' : 'these'} in {FMT || 'this format'}.
                    </b>{' '}
                    Not passes, not failures.
                  </>
                : <>Every selected criterion had a method for {FMT || 'this format'}.</>}
            </div>
          </div>
        </div>
        {/* The partition, printed. Either it holds on screen or the bug is visible to the reader
            rather than only to whoever reads the query. */}
        <div className="muted" style={{ marginTop: 12, paddingTop: 11, borderTop: '1px solid var(--line)',
                                        fontSize: 12 }}>
          {failing.size} failing + {passed.length} passed + {noMethod.length} no method
          {' = '}{r.selectedChecks} selected criteria
          {!identityHolds && (
            <b style={{ color: '#B3261E' }}> — these do not add up, which is a defect on this screen.</b>
          )}
        </div>
      </div>
    </section>
  )
}
