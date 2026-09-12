import RemediationLiveDocuments from './RemediationLiveDocuments.jsx'

// Retired from Release: assessment details remain available in Assess and Remediate.
export default function RetiredReleaseAssessmentDetails({run, releaseFiles, cap, assessment, publishedCount, progressDocuments}) {
  return (<details className="panel"><summary>Assessment findings and saved changes (optional)</summary>
      <RemediationLiveDocuments key={run?.id} scanId={run?.id} files={releaseFiles} cap={cap} assessment={assessment} refreshKey={publishedCount} progressDocuments={progressDocuments} />
      </details>)
}
