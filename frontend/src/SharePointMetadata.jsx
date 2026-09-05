// What SharePoint itself says about a document — and, for every field, whether ACP actually read
// it.
//
// THE SECOND HALF IS THE POINT. Every field here can be empty for two opposite reasons, and a
// panel that renders both as "—" invites the more damaging conclusion:
//
//   * SharePoint records nothing  → a fact about the customer's tenant, and an answer. No
//     retention labels are applied; the governance question is settled.
//   * ACP could not read it       → a fact about ACP, and a task. A missing scope, a Graph
//     version, a $select the tenant refuses.
//
// An operator who reads "Sensitivity label: —" and concludes their estate is unlabelled, when in
// truth nobody ever asked Graph for the labels, has been actively misled by this screen. So a
// field ACP could not read says so, in place of the value, with the reason underneath — and a
// field the tenant genuinely leaves unset says THAT, in different words.
//
// Renders nothing for a document with no SharePoint metadata at all: Google Drive, a local
// corpus, and every scan recorded before this shipped. Nothing to show is not the same as
// nothing set, and an empty panel full of "not recorded" rows on a Drive file would be noise
// that trains the reader to skip the panel on the files where it matters.
const LABELS = {
  site_name: 'Site',
  library_name: 'Document library',
  content_type: 'Content type',
  retention_label: 'Retention label',
  sensitivity_label: 'Sensitivity label',
  sharing_scope: 'Sharing',
  item_kind: 'Item type',
  checked_out_by: 'Checked out by',
  version: 'Version',
  modified_by: 'Last modified by',
  created_by: 'Created by',
  compliance_tag: 'Compliance tag',
  is_record: 'Declared a record',
  permissions: 'Permissions',
  managed_columns: 'Managed columns',
}

// The order a records manager reads them in — where it lives, what it is, how it is governed,
// then who touched it. Not alphabetical: "Content type" and "Retention label" are the two rows
// this panel exists for and they must not be buried between "Checked out by" and "Created by".
const ORDER = ['site_name', 'library_name', 'content_type', 'retention_label',
               'sensitivity_label', 'compliance_tag', 'is_record', 'managed_columns',
               'sharing_scope', 'permissions', 'item_kind', 'version', 'checked_out_by',
               'created_by', 'modified_by']

const fmt = (v) => {
  if (v === true) return 'Yes'
  if (v === false) return 'No'
  if (Array.isArray(v)) return v.join(', ')
  if (v && typeof v === 'object') {
    const pairs = Object.entries(v)
    return pairs.length ? pairs.map(([k, x]) => `${k}: ${x}`).join(' · ') : null
  }
  return v === null || v === undefined || v === '' ? null : String(v)
}

export default function SharePointMetadata({ metadata }) {
  const fields = metadata && typeof metadata === 'object' ? (metadata.fields || {}) : null
  if (!fields || Object.keys(fields).length === 0) return null

  const rows = ORDER.filter((k) => fields[k])
    // A field that cannot exist for this item is dropped rather than shown as "n/a": a OneDrive
    // file has no site, and a row saying so on every OneDrive document is a permanent reminder
    // of a non-problem.
    .filter((k) => fields[k].state !== 'not_applicable')
  if (rows.length === 0) return null

  const unread = rows.filter((k) => fields[k].state === 'unavailable')

  return (
    <>
      <h4 className="drawerh">SharePoint metadata</h4>
      {/* Said once, at the top, rather than only per row: a reader scanning for a value needs to
          know before they start that some of these blanks are ACP's and not their tenant's. */}
      {unread.length > 0 && (
        <p className="muted" style={{ fontSize: 12, margin: '0 0 8px' }}>
          {unread.length} field{unread.length === 1 ? '' : 's'} below could not be read from
          SharePoint. That is not the same as SharePoint recording nothing — each says why.
        </p>
      )}
      <div className="metagrid">
        {rows.map((k) => {
          const f = fields[k]
          const value = fmt(f.value)
          return (
            <div key={k} style={k === 'managed_columns' ? { gridColumn: '1 / -1' } : undefined}>
              <span className="muted">{LABELS[k] || k}</span>
              {f.state === 'present' && value !== null && (
                <b style={{ wordBreak: 'break-word' }}>{value}</b>
              )}
              {f.state === 'not_configured' && (
                // The tenant's own answer, in the tenant's terms. Deliberately NOT "—": a dash
                // is what an unread field would look like too.
                <b className="muted" style={{ fontWeight: 400 }}>SharePoint records none</b>
              )}
              {f.state === 'unavailable' && (
                <>
                  <b style={{ fontWeight: 400, color: 'var(--error-fg-strong)' }}>Not read</b>
                  {f.reason && (
                    <span className="muted" style={{ fontSize: 11, display: 'block', marginTop: 2 }}>
                      {f.reason}
                    </span>
                  )}
                </>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}
