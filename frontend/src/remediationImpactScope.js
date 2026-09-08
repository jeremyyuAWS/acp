// Planning must retain human-only and partially remediated documents. Only an
// explicit document selection or deferral narrows the assessment population here.
export function remediationImpactScope(files = [], triage = {}) {
  const selected = Object.values(triage).includes('inscope')
  return files.filter(file => file?.file && !['na', 'defer'].includes(triage[file.file])
    && (!selected || triage[file.file] === 'inscope'))
}
