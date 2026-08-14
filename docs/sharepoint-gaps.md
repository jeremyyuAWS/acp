# SharePoint support — what ACP does today vs. the UTSW pilot needs

**Context:** the UTSW / MOV pilot SOW scopes **up to 30 SharePoint locations**, a **full scan of all
locations** (no doc-count limit at scan; remediation capped at 500), **archival flagging only** with
**folder- / date- / user-based** rules, **daily** monitoring, and **SSO via Microsoft login** (single
tenant, Azure VPC). This maps that scope onto ACP's actual SharePoint code and names the gaps.

**Grounding:** verified in `api/scanner.py` and `api/disposition.py` on `main`, 2026-08-14. Companion to
`docs/sharepoint-app-registration.md` (access model), `docs/discovery-triage-spec.md` (buckets + ROT
rules), and `docs/pilot-scope.md`.

---

## What ACP supports today (verified)

- **Microsoft sign-in, delegated, read-only, single tenant** — MSAL Auth-Code+PKCE, scopes
  `User.Read` + `Files.Read.All` + `Sites.Read.All` (see `sharepoint-app-registration.md`). Matches the
  SOW's "SSO via Microsoft login (not AD)."
- **Site + library enumeration** — `GET /sites?search=…` (`scanner.py:456`), then
  `/sites/{site}/drives` (`:471`) to list each site's document libraries.
- **Scan of a site's libraries** — iterates every drive in a site (`/drives/{id}/root/search`,
  `:558`), reading each item's `id, name, file, parentReference` (so the **folder path is available**).
- **Folder skipping** — the scan already skips ACP's own archive + remediated-mirror folders
  (`skip_folders`, `:544`), i.e. a folder-scoped exclusion mechanism exists.
- **Disposition rule engine** — `api/disposition.py`: configurable `match` (AND) → `action`
  `{leave, archive, rename, move, delete}`, **approval-gated** (preview → `/execute`), **delete = Drive
  trash only** (never permanent). Matchable fields: `department, business_criticality, regulatory_tags,
  triage_score, source, owner, age_days`.
- **Scheduled re-scans** — `putSchedule(interval_minutes)`; **daily = 1440** satisfies the SOW cadence.
- **Non-applicable file types auto-flagged** — Discovery's filtered-by-type bucket (tiff, fonts, etc.),
  per `discovery-triage-spec.md`.

---

## Gaps (SOW requirement → ACP today → gap)

| SOW requirement | ACP today | Gap / effort |
|---|---|---|
| **Up to 30 SharePoint locations** | A scan targets **one site** (iterating its libraries) — `if site:` in `_sp_scope` (`scanner.py:556`) | **Biggest item — multi-site orchestration.** Either a multi-site scope or a job that fans 30 scans out as one. First: confirm whether a "location" = a **site** or a **library** (a site can hold many libraries, which ACP already scans together). |
| Full scan, no doc-count limit at scan | Batch path for large estates | **Not load-tested** at 30-location breadth (backlog **R11**) — exactly what `scripts/robustness_corpus.py` probes. |
| Auto-flag non-applicable types (tiff, PhD, fonts…) | Filtered-by-type bucket | ✅ supported |
| Archival rule: **date-based** | `age_days` match field | ✅ supported |
| Archival rule: **folder-based** | Folder path **is read** (`parentReference`); folder-skip exists — but the disposition engine has **no path/folder match field** | **Small build** — the data is already fetched; expose a `path`/`folder` rule field. |
| Archival rule: **user-based (departed employee)** | `owner` match field | **Partial** — owner match ✅; "departed" needs the **UTSW roster** as an input (the SOW puts rule-supply on UTSW). |
| **Smart archival — check active collaborators before flagging** | Not ingested | **Gap** — needs Graph **sharing/activity signals** (permissions / recent collaborators); extra reads, possibly extra scope. |
| **Read SharePoint-native metadata** (managed metadata, content types, retention/sensitivity labels) as rule inputs | Reads file basics + folder path only — **not** custom columns/labels | **Build (within read scopes)** — extend the item read to `listItem/fields`. This is the "rules using native capabilities" enabler. |
| **Tag files back into SharePoint's native columns** | Read-only. A native column write needs **`Sites.Manage.All` + per-library provisioning** — documented at `scanner.py:521` | **Out of scope by design for the pilot.** The SOW says archival is **flagging only** → ACP flags **internally** (its own store / approval queue). Native SharePoint write-back is **post-pilot** + a write scope. |
| Daily monitoring cadence | Scheduled re-scans | ✅ (1440 min) |
| SSO via Microsoft login, single tenant, Azure VPC | MSAL delegated, single-tenant per deploy | ✅ (VPC is infra config, not code) |

---

## "Rules in Discovery to tag files using native capabilities" — the read/write line

The SOW draws this line correctly, and the code agrees:

- **Reading native SharePoint metadata as rule inputs — YES, a build, within the read-only scopes.** The
  disposition engine already exists; extend its match inputs to `listItem/fields` (columns, content
  types, retention labels) **plus the folder path it already fetches**. That delivers folder-/date-/
  user-based rules keyed on SharePoint's own metadata, and it honors the customer's existing conventions
  (the `_ARCHIVED` folders and the "Archived on …" keyword — see `discovery-triage-spec.md §2`).
- **Writing tags back to SharePoint — NO for the pilot, by design.** Native column writes need
  `Sites.Manage.All` + per-library provisioning (`scanner.py:521`), which ACP avoids (read-only, PHI).
  The pilot is **flagging only**, so ACP records the tag **internally** and surfaces it in the
  approval-gated disposition queue — no write to the customer's SharePoint. Native write-back is a
  post-pilot decision with a scope change.

**Net:** tag-by-rule during the pilot = **read SharePoint-native metadata → apply a rule → flag
internally (approval-gated)**. That is a bounded build on top of the existing engine, entirely within
the read-only posture.

---

## Three things to surface in the SOW / "UTSW Responsibilities"

1. **Multi-site orchestration for the 30 locations** is the real engineering item. Confirm site-vs-library
   granularity and budget the multi-site scan; everything else is smaller.
2. **Native-metadata reads + folder/user rule fields** are small, high-value builds that directly enable
   the folder-/date-/user archival rules **UTSW will supply** — pair them with UTSW providing the rule
   definitions and the departed-employee roster.
3. **Image alt-text depends on the vision model, not the downloaded Llama.** Llama is a *text* model; WCAG
   1.1.1 needs a *vision* model, and the GPU path is currently down (backlog **R2/R12**), so image
   remediation falls to CPU/manual today. Set that expectation for the "image" half of the ~15 codes.

---

## Related backlog

- **R11** — multi-user / concurrency load test (the 30-location full-scan scenario).
- **R2 / R3 / R12** — RunPod vision not engaged (image alt-text degraded to CPU/manual).
- The **folder/native-metadata rule fields** and **multi-site scan** are new items this doc introduces;
  add them to `docs/BACKLOG.md` if the SOW is signed.
