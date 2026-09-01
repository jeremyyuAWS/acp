import { useState } from 'react'
import { patchAcrReport } from './acrApi'

// PRD §8's report metadata — the 21 fields a report needs before it can publish (§16:
// "Publication must fail if required information is missing").
//
// WHY THIS SCREEN EXISTS AT ALL. Phase 1 shipped the PATCH endpoint and a read-only Overview,
// which meant no report could ever reach a publishable state through the UI. That is not a
// missing nicety; it made the whole workflow terminate one step short.
//
// WHICH FIELDS ARE REQUIRED IS NOT HARDCODED HERE. It comes from the validation endpoint, which
// reports a blocking `incomplete_metadata` row per missing field, derived from
// acr_validation.REQUIRED_METADATA. A second hardcoded list in the frontend is exactly how the
// form ends up marking a field optional that the publish gate refuses — the same
// screen-disagrees-with-gate failure the criterion detail avoids by rendering the server's own
// refusal sentences. `blockingFields` is that list, passed in by the workspace.
//
// Advisory-but-empty fields (excluded functionality, known dependencies, general notes) come back
// as NON-blocking rows and are rendered as such: "confirm this is intentional", not "required".
// PRD's own reasoning — "no excluded functionality" is a real answer, and demanding prose for it
// trains people to type "n/a", which is worse than an empty field.

const GROUPS = [
  ['Product', ['report_title', 'product_name', 'product_version', 'build_id', 'release_date',
               'product_description']],
  ['Vendor', ['vendor_name', 'vendor_contact']],
  ['Scope', ['evaluation_scope', 'excluded_functionality', 'deployment_environment',
             'known_dependencies']],
  ['Standard', ['vpat_edition', 'wcag_version', 'wcag_levels']],
  ['Method', ['evaluation_methods', 'browsers_tested', 'operating_systems_tested',
              'assistive_technologies_tested', 'automated_tools']],
  ['Period and people', ['testing_period_start', 'testing_period_end', 'evaluators',
                         'general_notes']],
]

// Fields whose value is a date. Everything else is free text — deliberately, because PRD §8 asks
// for prose ("evaluation methods", "excluded functionality") and a constrained widget would
// invite a shorter answer than the field is for.
const DATE_FIELDS = new Set(['release_date', 'testing_period_start', 'testing_period_end'])
const LONG_FIELDS = new Set(['product_description', 'evaluation_scope', 'excluded_functionality',
                             'evaluation_methods', 'general_notes', 'known_dependencies'])

const label = (f) => f.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

export default function AcrMetadataForm({ report, blockingFields, advisoryFields, readOnly,
                                          onSaved }) {
  const [draft, setDraft] = useState({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [status, setStatus] = useState('')

  const value = (f) => (f in draft ? draft[f] : (report?.[f] ?? '')) ?? ''
  const dirty = Object.keys(draft).length

  const save = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const res = await patchAcrReport(report.id, draft)
      setDraft({})
      setStatus(`Saved ${res.updated} field${res.updated === 1 ? '' : 's'}.`)
      onSaved?.()
    } catch (err) { setError(String(err.message || err)) } finally { setBusy(false) }
  }

  const missing = blockingFields?.length || 0

  return (
    <form onSubmit={save}>
      <h3>Report information</h3>
      <p role="status" aria-live="polite">
        {missing
          ? `${missing} required field${missing === 1 ? '' : 's'} still empty — the report cannot be published until every one is filled in.`
          : 'Every required field is filled in.'}
        {status ? ` ${status}` : ''}
      </p>
      {error && <p role="alert" className="lockwarn">{error}</p>}

      {GROUPS.map(([group, fields]) => (
        <fieldset key={group}>
          <legend>{group}</legend>
          {fields.map((f) => {
            const isBlocking = blockingFields?.includes(f)
            const isAdvisory = advisoryFields?.includes(f)
            const id = `acr-meta-${f}`
            const hint = isBlocking ? `${id}-hint` : isAdvisory ? `${id}-adv` : undefined
            const common = {
              id,
              value: value(f),
              disabled: readOnly || busy,
              required: isBlocking,
              'aria-describedby': hint,
              onChange: (e) => setDraft({ ...draft, [f]: e.target.value }),
            }
            return (
              <div key={f}>
                <label htmlFor={id}>
                  {label(f)}
                  {/* Required is stated in words for a screen reader, not by the asterisk alone
                      — 1.4.1 and 3.3.2. */}
                  {isBlocking && <span aria-hidden="true"> *</span>}
                  {isBlocking && <span className="sr-only"> (required)</span>}
                </label>
                {LONG_FIELDS.has(f)
                  ? <textarea {...common} rows={3} />
                  : <input type={DATE_FIELDS.has(f) ? 'date' : 'text'} {...common} />}
                {isBlocking && (
                  <p id={hint} className="acr-refusal">Required before this report can publish.</p>
                )}
                {isAdvisory && (
                  <p id={hint} className="muted">
                    Empty is a valid answer — confirm it is intentional rather than typing "n/a".
                  </p>
                )}
              </div>
            )
          })}
        </fieldset>
      ))}

      {!readOnly && (
        <button type="submit" disabled={busy || !dirty}>
          {dirty ? `Save ${dirty} change${dirty === 1 ? '' : 's'}` : 'No changes'}
        </button>
      )}
      {readOnly && (
        <p className="muted">
          This report is published, or you do not hold the editor role. Metadata is read-only.
        </p>
      )}
    </form>
  )
}
