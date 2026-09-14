import EstateProgressPanel from './EstateProgressPanel.jsx'
import NextStep from './NextStep.jsx'
import AccordionSection from './AccordionSection.jsx'
import AssertionScope from './AssertionScope.jsx'
import { CORE_SCS } from './activeScope.js'
import { analysedCount } from './docStatus.js'
import { remediableCount } from './sim.js'
import { reconcileBuckets, assessmentEligible } from './estateFunnel.js'
import { reconciliationInputs } from './reconciliationInputs.js'
import { assessMetrics, coverageSentence, SEVERITIES, SEVERITY_LABEL } from './assessMetrics.js'

// Retired from Overview on 2026-09-14 at the owner's request. Deliberately not mounted.
// Preserve the previous workflow and assessment panels for an explicit future restoration.
export default function RetiredOverviewWorkflow({ run, files = [], estateFiles = files, onGo, cap, assessment }) {
  const n = run.files || 0
  const analysed = analysedCount(files)
  const stageAssessed = analysed > 0
  const needFix = remediableCount(files)
  const publish = files.filter(file => file.published_at).length
  const rec = reconcileBuckets(run?.scope?.inventory, reconciliationInputs(run, files))
  const metrics = assessMetrics(files, { cap, assessment })
  const sevAddends = metrics ? [...SEVERITIES.map(s => metrics.bySeverity[s]), ...(metrics.bySeverity.UNKNOWN > 0 ? [metrics.bySeverity.UNKNOWN] : [])] : []
  const lifecycleBucket = rec?.rows.find(row => row.key === 'lifecycle')
  const lifecycleAwaiting = lifecycleBucket?.measured ? lifecycleBucket.value : null
  const eligible = assessmentEligible(run?.scope?.inventory)
  const hasEstateProgress = run?.scope?.inventory?.discovered != null || files.length > 0
  const scopePanel = <AssertionScope run={run} fileCount={files.length || eligible || 0} coreScs={CORE_SCS} rec={rec} />
  return (
      <details className="balanced-legacy"><summary>Workflow and assessment details</summary>
      <EstateProgressPanel
        inventory={run.scope?.inventory}
        analysed={analysed}
        needFix={needFix}
        certifiable={run.certifiable}
        published={publish}
        errorCount={run.error}
        files={files}
        estateFiles={estateFiles}
        onGo={onGo}
        collapsible
        afterProgress={hasEstateProgress ? scopePanel : null}
      />

      {/* ── ASSESSMENT — the section that grows in once documents have actually been assessed.
             Below discovery, above the detailed findings charts. Before a run it is a prompt, not an
             empty grid; after one it is the seven metrics (board 4), read from the SAME assessMetrics
             the Assess tab reports so one run never shows two different totals across two tabs. ── */}
      {stageAssessed && metrics ? (
        <>
          {/* Supporting assessment evidence stays collapsed. Its concise coverage summary remains
              visible in the header; the four estate stages above own the open headline view. */}
          <AccordionSection id="assessment-summary" className="panel overview-assessment"
                            ariaLabel="Assessment summary" defaultOpen={false}
                            title="Assessment" meta={coverageSentence(metrics)}>
              <>
                <div className="metrics">
                  <div className="metric" title="Documents where at least one selected check completed.">
                    <span>documents assessed</span><b>{metrics.documentsAssessed}</b></div>
                  <div className="metric" title="Assessed documents carrying at least one unresolved finding.">
                    <span>needing attention</span><b style={{ color: 'var(--warn-fg)' }}>{metrics.documentsNeedingAttention}</b></div>
                  <div className="metric" title="Unresolved finding instances across all assessed documents. One criterion can produce many.">
                    <span>total findings</span><b>{metrics.totalFindings}</b></div>
                  <div className="metric" title="Findings with a deterministic remediation — same input, same fix, no person needed.">
                    <span>auto-fix available</span><b style={{ color: '#2F7D32' }}>{metrics.autoFixAvailable}</b></div>
                  <div className="metric" title="Findings needing a person's judgement, including every AI-drafted fix awaiting approval.">
                    <span>human review required</span><b>{metrics.humanReviewRequired}</b></div>
                  <div className="metric" title="Selected checks that could not run — no method for these formats. Not passes and not failures.">
                    <span>unable to assess</span><b>{metrics.unableToAssess} <span className="muted" style={{ fontWeight: 400, fontSize: 12 }}>checks</span></b></div>
                </div>
                {/* The severity partition, added up on screen — the 7th metric, printed as an equation so
                    a reader can check it against Total findings rather than take it on trust. */}
                {metrics.totalFindings > 0 && (
                  <div className="muted" style={{ fontSize: 12.5, marginTop: 8 }}>
                    By severity: {SEVERITIES.map((s, i) => (
                      <span key={s}>{i > 0 ? ' · ' : ''}<b>{metrics.bySeverity[s]}</b> {SEVERITY_LABEL[s]}</span>
                    ))} — {sevAddends.join(' + ')} = {metrics.totalFindings}
                  </div>
                )}
              </>
          </AccordionSection>

          {/* SO WHAT NOW (board 7). The only panel on this screen with a primary action. */}
          <NextStep metrics={metrics}
                    awaiting={lifecycleAwaiting}
                    onRemediate={() => onGo && onGo('remediate')}
                    onReviewLifecycle={() => onGo && onGo('discover')} />
        </>
      ) : (
        <AccordionSection id="assessment-summary" className="panel overview-runassess"
                          ariaLabel="Assessment not yet run" defaultOpen
                          title="Assessment" meta="not yet run">
          {(n > 0 ? (
            <>
              <p className="muted" style={{ margin: '4px 0 12px' }}>
                {n.toLocaleString()} document{n === 1 ? '' : 's'} discovered
                {eligible != null && eligible < n && ` · ${eligible.toLocaleString()} eligible for WCAG assessment`}.{' '}
                Run an assessment to score them against WCAG 2.1 — findings, coverage and the
                severity breakdown appear here once it finishes.
              </p>
              <button onClick={() => onGo && onGo('assess')}>Run assessment →</button>
            </>
          ) : (
            <p className="muted" style={{ margin: '4px 0 0' }}>
              No documents have been discovered yet. Configure a source and run a scan from
              the Discover tab first.
            </p>
          ))}
        </AccordionSection>
      )}

      </details>
  )
}
