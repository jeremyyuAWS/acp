// Auto-escalation numbered path (P1 HITL copilot) — derived ONLY from the real per-call AI ledger
// (ai_calls rows: surface / provider / model / zone / ok), never fabricated.
//
// The backend (api/ai.py describe_image → _escalate_vision, ADR 0019 §3c) escalates a vision draft
// to a governed cloud provider ONLY when the local model could not GROUND a description, and traces
// both the local attempt and the cloud call to ai_calls. So when this file's vision-surface ledger
// carries a local attempt AND a cloud call, that IS an escalation — the local attempt is not a dead
// end, it is step one of a transparent path. This reads that path back off the ledger so the card
// can show "✓ local attempted → no grounded description → escalated to {provider} → grounded"
// instead of surfacing the failed local attempt on its own.
//
// Returns null when there was no escalation (no cloud vision row) — the common, all-local case.
export function escalationPath(rows) {
  const vision = (rows || []).filter((r) => r && r.surface === 'vision')
  if (vision.length < 2) return null
  // The local attempt (the model that couldn't ground) and the cloud call it escalated to. The
  // backend only ever makes a cloud VISION call as an escalation after a local one, so the presence
  // of both — regardless of the array's ordering — is the escalation signal.
  const local = vision.find((r) => r.zone === 'local')
  const cloud = vision.find((r) => r.zone && r.zone !== 'local')
  if (!local || !cloud) return null
  return {
    provider: cloud.provider || 'cloud',
    cloudModel: cloud.model || null,
    localModel: local.model || null,
    localZone: local.zone || 'local',
    cloudZone: cloud.zone || 'cloud',
    // Did the cloud escalation actually produce a description? A cloud row is still traced when the
    // call itself failed (ai.py traces before the ok check), so an honest path must say "cloud
    // unavailable" rather than claim "grounded" when the escalation did not land.
    cloudOk: cloud.ok !== false,
    source: 'ledger',
  }
}

// The SAME path, read directly from a /ai/suggest draft response (#378) — the PREFERRED source over
// the ledger. api/ai.py forwards `provider` + `processing_zone` on every real vision draft, and
// attaches the numbered `escalation` steps (+ `cost_usd`) ONLY when a cloud escalation actually
// occurred (_escalate_vision returned a usable cloud description). So a response carrying a non-empty
// `escalation` array IS an escalation — read it back into the same shape escalationPath() returns, so
// one render path serves both sources. Null when the draft did not escalate (a plain local vision
// draft, a template, or a non-vision draft) — the card then falls back to the ledger-derived path.
//
// The steps are the backend's own transparent path: [{provider,zone,outcome:'no grounded description'},
// {provider,zone,outcome:'produced a description',cost_usd}]. The cloud provider/model/zone are also
// mirrored onto the top-level response (provider / model / processing_zone / cost_usd), which is what
// the card actually renders; the steps confirm the escalation happened and carry the outcome.
export function escalationFromDraft(resp) {
  const steps = resp && Array.isArray(resp.escalation) ? resp.escalation : null
  if (!steps || steps.length < 2) return null
  const localStep = steps[0] || {}
  const cloudStep = steps[steps.length - 1] || {}
  return {
    provider: resp.provider || cloudStep.provider || 'cloud',
    // The draft's `model` is the model that produced the FINAL alt — the cloud model, once escalated
    // (api/ai.py describe_image sets model_used = esc.model on escalation).
    cloudModel: resp.model || cloudStep.model || null,
    localModel: localStep.model || null,
    localZone: localStep.zone || 'local',
    cloudZone: resp.processing_zone || cloudStep.zone || 'cloud',
    // The steps are attached only when the cloud call produced a usable description, so a draft that
    // reached the card grounded. Read the outcome anyway rather than assume, so a future "cloud
    // unavailable" step renders honestly, exactly as the ledger path does.
    cloudOk: !/unavailable|fail|could ?n.?t|error/i.test(cloudStep.outcome || ''),
    costUsd: typeof resp.cost_usd === 'number' ? resp.cost_usd : (cloudStep.cost_usd ?? null),
    source: 'draft',
  }
}
