// Accessibility Conformance Report (ACR) API client — ADR 0047, PRD Phase 1.
//
// Deliberately thin. Every conformance judgement is the backend's: which statuses are permitted,
// why one is refused, what blocks publication. This module fetches and returns; it never decides,
// and it never re-derives a refusal reason locally. That is the whole reason the criterion-detail
// endpoint returns `assessment.refusals` as SENTENCES rather than codes — the screen renders the
// server's own words, so a user can never be shown a different explanation from the one the POST
// would give them.
import { getToken } from './api'

const BASE = import.meta.env.VITE_API ?? 'http://localhost:8077'

const headers = (extra = {}) => {
  const token = getToken()
  return { ...extra, ...(token ? { Authorization: 'Bearer ' + token } : {}) }
}

async function call(path, { method = 'GET', body } = {}) {
  const res = await fetch(BASE + path, {
    method,
    headers: headers(body ? { 'Content-Type': 'application/json' } : {}),
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  if (!res.ok) {
    // The backend's refusals are the user-facing explanation (a 422 from the decision endpoint
    // carries the decision rule's own sentence). Surfacing `detail` verbatim is what keeps the
    // screen and the gate telling one story.
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* non-JSON error body — keep the status line */ }
    const err = new Error(detail)
    err.status = res.status
    throw err
  }
  return res.status === 204 ? null : res.json()
}

export const listAcrReports = () => call('/acr')
export const createAcrReport = (metadata) => call('/acr', { method: 'POST', body: { metadata } })
export const getAcrReport = (id) => call(`/acr/${id}`)
export const patchAcrReport = (id, fields) => call(`/acr/${id}`, { method: 'PATCH', body: { fields } })
export const listAcrCriteria = (id) => call(`/acr/${id}/criteria`)
export const getAcrCriterion = (id, num) => call(`/acr/${id}/criteria/${num}`)
export const getAcrValidation = (id) => call(`/acr/${id}/validation`)
export const getAcrAudit = (id) => call(`/acr/${id}/audit`)
export const getAcrPreview = (id) => call(`/acr/${id}/preview`)
export const getAcrGaps = (id) => call(`/acr/${id}/gaps`)

// Guided manual test plans (PRD §14, Phase 3).
export const getCriterionPlans = (id, num) => call(`/acr/${id}/criteria/${num}/plans`)
export const startPlanRun = (id, num, planId, tester) =>
  call(`/acr/${id}/criteria/${num}/plans/start`,
       { method: 'POST', body: { plan_id: planId, tester } })
export const recordPlanStep = (id, runId, stepIndex, outcome, notes) =>
  call(`/acr/${id}/plans/runs/${runId}/step`,
       { method: 'POST', body: { step_index: stepIndex, outcome, notes } })
export const completePlanRun = (id, runId, body) =>
  call(`/acr/${id}/plans/runs/${runId}/complete`, { method: 'POST', body })

// Publication and revisions (PRD §16–17, Phase 4).
export const getAcrPublication = (id) => call(`/acr/${id}/publication`)
export const publishAcr = (id) => call(`/acr/${id}/publish`, { method: 'POST', body: {} })
export const getAcrRevisions = (id) => call(`/acr/${id}/revisions`)
export const getAcrRevision = (id, n) => call(`/acr/${id}/revisions/${n}`)
export const reviseAcr = (id) => call(`/acr/${id}/revise`, { method: 'POST', body: {} })

// `preview: true` reports what would be written without writing it. Worth defaulting callers
// toward: acr_evidence is append-only, and the interesting part of an axe ingest is what it
// DROPS — inapplicable rules are not evidence, and a user should see that before committing
// a few hundred rows.
export const ingestAxe = (id, result, opts = {}) =>
  call(`/acr/${id}/evidence/axe`, { method: 'POST', body: { result, ...opts } })

export const setAcrApplicability = (id, num, applicable, rationale) =>
  call(`/acr/${id}/criteria/${num}/applicability`,
       { method: 'POST', body: { applicable, rationale } })

export const addAcrEvidence = (id, num, evidence) =>
  call(`/acr/${id}/criteria/${num}/evidence`, { method: 'POST', body: { criterion_num: num, ...evidence } })

export const decideAcrCriterion = (id, num, finalStatus, remarks) =>
  call(`/acr/${id}/criteria/${num}/decision`, { method: 'POST', body: { final_status: finalStatus, remarks } })

export const approveAcrCriterion = (id, num) =>
  call(`/acr/${id}/criteria/${num}/approve`, { method: 'POST' })

// The four VPAT terms, in the order a VPAT table presents them. Mirrored from the backend's
// acr_catalog.FINAL_STATUSES rather than invented here — PRD §9 forbids additional statuses, and a
// second list is how a fifth one appears in a dropdown. acrVocabulary.test.js pins them equal.
export const FINAL_STATUSES = ['Supports', 'Partially Supports', 'Does Not Support', 'Not Applicable']

// Statuses whose remarks are mandatory (PRD §10). Used only to mark the field required in the UI —
// the backend refuses regardless, so this is a courtesy, never the enforcement.
export const REMARKS_REQUIRED = ['Partially Supports', 'Does Not Support', 'Not Applicable']
