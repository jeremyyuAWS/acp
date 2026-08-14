# Discovery & triage — spec

**Purpose:** Discovery should scan the *whole* source and sort **every file into exactly one honest
bucket** — assessable, filtered by type, already-archived, ROT (archive/delete candidate), or
unreadable — so remediation scope only ever contains files worth certifying. This spec defines the
buckets, the triage triggers, which signals ACP can actually read, and the guardrails.

**Status:** proposed. **Grounding:** the current lifecycle (`retentionOf`, `FileDrawer.jsx`) and the
Disposition policy engine (Disposition tab) are the starting point; where a trigger needs a signal ACP
doesn't yet ingest, this says so.

---

## 0. Context — the customer has already archived 17,512 files (honor it)

The customer completed a manual archiving pass (per their 2026-01-24 note): **17,512 files**, using a
convention ACP should recognize out of the box:

- **Files renamed** `xxxx.yyy → xxxx_ARCHIVED.yyy`
- **Folders renamed** `xxxx → xxxx_ARCHIVED`
- **Metadata keywords** added: `"Created before April 24, 2026"`, `"Archived on 01/24/2026"`
- A **master list** ("DA – Content Inventory") tracks each file's status.

**The single most valuable thing Discovery can do here: detect and honor that convention automatically.**
ACP must NOT re-assess, re-flag, or re-triage those 17,512 files — they are already dispositioned. See §2.

---

## 1. The reconciling bucket model

Every file lands in **exactly one** bucket, and the buckets **sum to the estate total** — "scan complete"
must account for every file, with no silent drops.

| Bucket | Meaning | Next action |
|---|---|---|
| **A · Assessable + remediable** | supported type with an active remediation lane (DOCX full; PDF/PPTX/XLSX partial) | Assess → Remediate |
| **B · Assessable, assess-only** | supported type, but its findings are human-only for that format | Assess → human review |
| **C · Already archived** | matches the customer's archive convention (§2) — already dispositioned | Exclude from scope (no re-processing) |
| **D · Triage candidate (ROT)** | a document ACP *could* assess but shouldn't — Redundant / Obsolete / Trivial (§3) | Review → archive/trash (approval-gated) |
| **E · Filtered by file type** | not a document (image, audio, video, CAD, archive) — out of accessibility scope | Report count; optional custom exclusion |
| **F · Unreadable** | password-protected / corrupt / encrypted | Fix at source / re-upload |

**Order of operations:** classify → recognize already-archived (C) → ROT triage (D) → **then** assess the
survivors (A/B). Triaging before assessment is what "reduces remediation scope" — you never spend
remediation effort on a file that shouldn't exist or is already archived.

---

## 2. Recognize already-archived content (highest-value, lowest-cost trigger)

Auto-classify into **bucket C** — never assessed, never ROT-flagged — when ANY of:

1. **Filename suffix** — base name ends in `_ARCHIVED` before the extension (`*_ARCHIVED.*`).
2. **Folder path** — any ancestor folder ends in `_ARCHIVED` (the whole subtree is archived).
3. **Metadata keyword** — the file's SharePoint metadata/keywords contain `Archived on <date>` (or a
   configurable archive-tag term).

Make the suffix/keyword **configurable** (a customer may use `_ARCHIVE`, `ZZ_`, a retention label, etc.) —
default to `_ARCHIVED` for this customer. Show the recognized-archived count prominently in the Discovery
summary ("17,512 already archived — excluded from scope") so the customer sees ACP respected their work.

**Reconcile with the master list (stretch):** if the customer can share "DA – Content Inventory" (CSV),
Discovery can cross-check its own archived-set against theirs and surface **drift** — files marked archived
in the list but not renamed, or renamed but missing from the list. That reconciliation is a governance
artifact they'd value; keep it read-only and advisory.

---

## 3. ROT triggers (for the not-yet-archived remainder)

Each flag is a **recommendation**, gated by approval, with a plain-language reason. Grouped by type:

**Redundant**
- **Exact duplicate** — content-hash match across locations (high confidence, auto-suggest).
- **Superseded version** — same title/name stem with `v1/v2/final/copy of/(1)` and a newer sibling exists.
- **Old copy of an approved template/form** when a newer approved one exists in the estate.

**Obsolete**
- **Stale by last-modified** — not edited in *N* days (lifecycle default ≥540; configurable). Pairs well
  with the customer's own "Created before April 24, 2026" cutoff — expose a **date-cutoff trigger** so
  they can replay that exact rule.
- **No engagement** — low/zero opens in 90 days (`retentionOf` already pairs age with `views90d < 60`).
- **Orphaned owner** — owner has left the org (ties to the Users/Owners lists).
- **Past retention / expired** — a retention date or policy label.
- **Deprecation signal in content** — mentions a retired brand/system/policy (content-based → review only).

**Trivial**
- **Empty / near-empty** — blank docs, empty worksheets (`BlankWorksheetRule` already detects), near-zero
  character count.
- **System/junk artifacts** — `.tmp`, `~$` lock files, `thumbs.db`, `.DS_Store`, auto-exports, logs.
- **Scratch/personal** — "untitled", "test", "copy of copy", unreferenced drafts.

---

## 4. Signal availability — only trigger on what we can actually read

Read-only Graph/Drive scopes reliably expose some signals and not others. Trigger only on real signals;
never fabricate one.

| Signal | Source | Available now? |
|---|---|---|
| Filename / path / extension | Drive/Graph item | ✅ |
| `createdDateTime` / `lastModifiedDateTime` | Graph item | ✅ |
| Size | Graph item | ✅ |
| Owner / createdBy | Graph item | ✅ |
| SharePoint metadata / keywords (archive tags) | Graph `listItem/fields` | ✅ (columns must be readable) |
| Content hash (dedup) / blank detection / keywords | file bytes (already downloaded to scan) | ✅ |
| **Views / last-accessed / access analytics** | Graph analytics / `getActivitiesByInterval` | ⚠️ needs extra endpoints/permissions — flag as "if tenant grants analytics" |
| **Version history** (supersession) | Graph `versions` | ⚠️ additional call; confirm scope |

Where a signal is `⚠️`, label the trigger "available if enabled" rather than shipping a fabricated view
count — consistent with the read-only, no-standing-access posture in `docs/sharepoint-app-registration.md`.

---

## 5. Guardrails (what makes it trustworthy)

1. **Recommendation, never auto-delete.** Every ROT flag goes to the approval queue; **delete only ever
   moves to trash (recoverable)** — the Disposition tab already enforces this. **Legal-hold / locked files
   are never flagged** (`retentionOf` already exempts them).
2. **Explainable per file.** Each flag names its trigger: *"Obsolete — not modified in 3.2 yrs, 0 opens in
   90 days"* / *"Redundant — byte-identical to /Policies/HR-v3.docx"* / *"Already archived — folder
   `/HR/2019_ARCHIVED`."*
3. **Confidence tiers.** High-confidence (exact dup, empty, `_ARCHIVED`, past-retention) may be
   pre-selected; heuristic (age + low-access) stays review-only. A fuzzy signal never auto-archives.
4. **Configurable, per-owner-overridable policy.** Extend the Disposition rule builder ("when age > X →
   action, require approval per file") to the ROT trigger set + the archive-convention terms — don't
   hard-code thresholds.
5. **Reconcile counts.** The C/D counts feed the same estate breakdown; the total always sums.
6. **"Applicable for remediation" is a projection until assessed.** Discovery projects applicability from
   type + the capability matrix, but labels it a projection — it doesn't promise a fix pre-assessment
   (same principle as "unsupported ≠ passing").

---

## 6. Output — the estate coverage report

A single exportable artifact (CSV + PDF) compliance can hand off:

- **Rollup:** total files → A/B/C/D/E/F counts (reconciling to the total), with the already-archived and
  ROT counts called out.
- **Per file:** path, type, bucket, the trigger/reason, owner, last-modified, and (for A/B) projected SC
  coverage from the capability matrix.
- **Type rollup:** for each supported type present, what ACP can do (auto/assisted/human SC counts).

---

## 7. Build order (suggested)

1. **Bucket model + already-archived recognition (§1–2)** — cheapest, highest value, honors the 17,512.
   Ship the `_ARCHIVED` suffix/folder/keyword detector + the reconciling summary first.
2. **High-confidence ROT (§3):** exact-duplicate hash, empty-file, date-cutoff (replays their "before
   April 24, 2026"), system-junk. All metadata/content-based → no extra scopes.
3. **The estate coverage report (§6).**
4. **Heuristic ROT + analytics signals (§3–4):** age+low-access, supersession, orphaned-owner — gated on
   confirming the analytics/versions Graph scopes.
5. **Master-list reconciliation (§2).**
