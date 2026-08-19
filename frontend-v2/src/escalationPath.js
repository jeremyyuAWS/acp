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
  }
}
