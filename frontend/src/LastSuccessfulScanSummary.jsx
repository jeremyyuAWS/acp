const nf = new Intl.NumberFormat('en-US')

const sourceLabel = (source) => ({
  drive: 'Google Drive',
  sharepoint: 'SharePoint / OneDrive',
  local: 'Local corpus',
  smb: 'Network folders',
}[source] || (source ? String(source) : 'Not recorded'))

function folderSummary(scope) {
  if (!scope) return { value: 'Not recorded', detail: 'This scan predates recorded scope details.' }
  const chosen = (scope.folders || []).map((folder) => folder?.name).filter(Boolean)
  if (scope.folder_name && !chosen.includes(scope.folder_name)) chosen.unshift(scope.folder_name)
  const walked = Number(scope.folders_walked)

  if (chosen.length) {
    return {
      value: `${chosen.length} selected`,
      detail: `${chosen.join(', ')}${walked > chosen.length ? ` · ${nf.format(walked)} folders traversed` : ''}`,
    }
  }
  if (Number.isFinite(walked) && walked > 0) {
    return { value: nf.format(walked), detail: `folder${walked === 1 ? '' : 's'} traversed` }
  }
  if (scope.kind === 'drive') return { value: 'Whole Drive', detail: 'No folder restriction' }
  if (scope.kind === 'sharepoint' && scope.site_name) return { value: scope.site_name, detail: 'Whole selected site' }
  if (scope.kind === 'sharepoint') return { value: 'Whole OneDrive', detail: 'No folder restriction' }
  if (scope.kind === 'local') return { value: 'Local corpus', detail: scope.path || 'Configured corpus path' }
  return { value: 'Not recorded', detail: 'No folder boundary was stored.' }
}

function criteriaSummary(scope) {
  if (!scope || !Object.prototype.hasOwnProperty.call(scope, 'scan_scope')) {
    return { value: 'Not recorded', detail: 'Criteria were not preserved on this historical run.' }
  }
  if (scope.scan_scope == null) return { value: 'All criteria', detail: 'No WCAG criterion restriction' }
  const entries = Object.entries(scope.scan_scope || {})
  const formats = [...new Set(entries.flatMap(([, values]) => Array.isArray(values) ? values : []))]
    .map((value) => String(value).toUpperCase()).sort()
  return {
    value: `${nf.format(entries.length)} criteria`,
    detail: formats.length ? formats.join(', ') : 'No document formats recorded',
  }
}

function lifecycleSummary(scope) {
  if (!scope || scope.lifecycle_rules_enabled == null) {
    return { value: 'Not recorded', detail: 'Lifecycle execution details are unavailable.' }
  }
  const rules = Number(scope.lifecycle_rules_enabled) || 0
  const archive = Number(scope.lifecycle_archive) || 0
  const remove = Number(scope.lifecycle_delete) || 0
  const tagged = Number(scope.lifecycle_tagged) || 0
  const outcomes = []
  if (archive) outcomes.push(`${nf.format(archive)} archive`)
  if (remove) outcomes.push(`${nf.format(remove)} deletion`)
  if (tagged) outcomes.push(`${nf.format(tagged)} tagged`)
  return {
    value: rules ? `${nf.format(rules)} enabled` : 'No enabled rules',
    detail: outcomes.length ? outcomes.join(' · ') : 'No lifecycle candidates produced',
  }
}

function ScanTile({ label, value, detail }) {
  return (
    <div style={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 12,
                  padding: '14px 16px', minWidth: 0 }}>
      <div style={{ color: 'var(--muted)', fontSize: 12, textTransform: 'uppercase',
                    letterSpacing: '0.04em', fontWeight: 600 }}>{label}</div>
      <div style={{ color: 'var(--ink)', fontSize: 19, fontWeight: 700, lineHeight: 1.2,
                    marginTop: 6, overflowWrap: 'anywhere' }}>{value}</div>
      <div className="muted" style={{ fontSize: 12, lineHeight: 1.4, marginTop: 5,
                                       overflowWrap: 'anywhere' }}>{detail}</div>
    </div>
  )
}

export default function LastSuccessfulScanSummary({ run = null, scope = null, runAt = null }) {
  // Assessment/remediation advance the run beyond the literal "discovered" status. The durable
  // discovery timestamp is the proof that a listing succeeded; terminal failure states without
  // that timestamp must never be presented as the last successful scan.
  if (!run || (!run.discovered_at && run.status !== 'discovered')) return null
  const folders = folderSummary(scope)
  const criteria = criteriaSummary(scope)
  const lifecycle = lifecycleSummary(scope)
  const enumeration = scope?.enumeration
  const complete = enumeration?.complete === true && !scope?.truncated

  return (
    <section aria-labelledby="last-successful-scan-heading" style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                    gap: 10, flexWrap: 'wrap', marginBottom: 9 }}>
        <h3 id="last-successful-scan-heading" style={{ margin: 0, fontSize: 14 }}>
          Last successful scan
        </h3>
        <span className="muted" style={{ fontSize: 12 }}>
          Scan ID {run.id || 'not recorded'}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))',
                    gap: 10 }}>
        <ScanTile label="Completed" value={runAt?.recorded ? runAt.absolute : 'Time not recorded'}
                  detail={`${sourceLabel(run.source)}${runAt?.recorded ? ` · ${runAt.relative}` : ''}`} />
        <ScanTile label="Folders scanned" value={folders.value} detail={folders.detail} />
        <ScanTile label="Assessment scope" value={criteria.value} detail={criteria.detail} />
        <ScanTile label="Lifecycle rules" value={lifecycle.value} detail={lifecycle.detail} />
        <ScanTile label="Enumeration" value={complete ? 'Complete' : scope?.truncated ? 'Partial' : 'Not verified'}
                  detail={enumeration?.files_found != null
                    ? `${nf.format(enumeration.files_found)} files found at the source`
                    : 'Completion evidence was not recorded'} />
      </div>
    </section>
  )
}
