# PRD — Per-Scan Decision Snapshots ("Time-Travel")

Status: **In progress** · Owner: platform · Created: 2026-06-29

## 1. Problem
Time-travel (the scan picker) switches the read-only **data** view to any past scan,
but the **decisions** a user makes — triage (in-scope / N/A / defer) and remediation
(accept / override / reject) — are ephemeral client state keyed to the current
session. They don't persist and don't rewind. So a user cannot revisit a past scan
and see "what I had decided then," and all decisions are lost on reload.

## 2. Goal
Persist user decisions **per scan** so that time-traveling to any scan restores that
scan's full state — data **and** decisions — across every tab, and make it intuitive:
loading and saving are automatic, and the UI clearly signals which scan is in view and
that its decisions were restored.

## 3. Non-goals
- Branching / merging decision sets across scans.
- Multi-user collaborative editing of one scan's decisions (decisions are owner-scoped,
  single editor; last-write-wins).
- Full per-edit version history (we store the latest decision per file, not every edit).

## 4. UX (intuitive by default)
- The 🕐 **Time-travel** picker loads a scan **and its persisted decisions** automatically.
- A banner shows **"Viewing the scan from `<date>` — N decisions restored."**
- Decisions **save automatically** as they're made — no Save button — with a subtle
  "saved" cue.
- **Every tab** (Discover action plan, Remediate triage + HITL, dashboards) reflects the
  loaded scan's decisions.
- Each scan is its **own working set**: editing a past scan's decisions updates that
  scan's snapshot, not the latest.

## 5. Data model
`scan_decisions(scan_id, file, kind, value, owner_email, updated_at, PRIMARY KEY(scan_id, file, kind))`
- `kind = 'triage'` → `value ∈ {inscope, na, defer}`
- `kind = 'action'` → `value = JSON {state, action}` (remediation decision)
- Owner-scoped (inherits the scan's owner; reads are filtered by owner, like scans).

## 6. API (owner-scoped)
- `GET /scans/{sid}/decisions` → `{ file: { triage?, action? } }`
- `PUT /scans/{sid}/decisions/{file}?kind=triage|action` body `{value}` → upsert
- `DELETE /scans/{sid}/decisions/{file}?kind=…` → clear one (undo)

## 7. Frontend
- On scan load (initial **and** time-travel `switchScan`): fetch decisions → hydrate the
  App `decisions` map + Remediate `triage` map.
- On decision change: persist (debounced) to the backend for the active scan.
- Time-travel banner + "decisions restored / saved" indicator.

## 8. Phases
1. **Backend** — `scan_decisions` table + GET/PUT/DELETE API, owner-scoped. ← **start here**
2. **Frontend** — hydrate on scan load, save on change; wire `decisions` + `triage` per scan.
3. **UX polish** — time-travel banner ("viewing scan from X · N decisions restored"),
   saved indicator, clear "you're viewing history" cue.
4. *(Optional)* include the decision snapshot in the exported PDF report.

## 9. Open questions
- Past-scan decisions: read-only (view history) or editable (revise)? **Proposed: editable**
  — each scan is its own set; editing updates that scan's snapshot.
- Same user, two browser tabs, same scan → last-write-wins (acceptable).
