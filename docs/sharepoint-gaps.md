# SharePoint support — what ACP does today vs. the UTSW pilot needs

**Context:** the UTSW / MOV pilot SOW scopes **up to 30 SharePoint locations**, a **full scan of all
locations** (no doc-count limit at scan; remediation capped at 500), **archival flagging only** with
**folder- / date- / user-based** rules, **daily** monitoring, and **SSO via Microsoft login** (single
tenant, Azure VPC). This maps that scope onto ACP's actual SharePoint code and names the gaps.

**Grounding:** verified in `api/scanner.py` and `api/disposition.py` on `main`, 2026-08-14; the multi-site
rows re-verified 2026-09-04 against the change that closed them. Companion to
`docs/sharepoint-app-registration.md` (access model), `docs/discovery-triage-spec.md` (buckets + ROT
rules), and `docs/pilot-scope.md`.

---

## What ACP supports today (verified)

- **Microsoft sign-in, delegated, read-only, single tenant** — MSAL Auth-Code+PKCE, scopes
  `User.Read` + `Files.Read.All` + `Sites.Read.All` (see `sharepoint-app-registration.md`). Matches the
  SOW's "SSO via Microsoft login (not AD)."
- **Site + library enumeration** — `GET /sites?search=…` (`scanner.py:456`), then
  `/sites/{site}/drives` (`:471`) to list each site's document libraries.
- **Scan of a site's libraries** — iterates every drive in a site, reading each item's
  `id, name, file, parentReference` (so the **folder path is available**). The route is
  `/root/children` — a walk against live metadata — not `/root/search`, which reads the
  eventually-consistent search index and under-reports a recently-changed library with no error.
- **Multi-site scans (2026-09-04)** — one Discovery run covers up to 30 sites (`ACP_SP_MAX_SITES`),
  walking every document library on each under one shared file budget. Each document records the
  site, library, drive and item it came from (`scan_inventory.site_id` / `library_name`); one
  site's 403 or throttle is isolated to that site and the run continues; and the scan's scope
  carries a per-site breakdown — libraries, counts, status (`complete` / `partial` / `blocked` /
  `skipped`) and the error — so "no site was silently omitted" is checkable rather than asserted.
  Per-site progress reaches the SSE stream as each site resolves.
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
| **Up to 30 SharePoint locations** | ✅ **Built 2026-09-04.** One run spans up to 30 sites (`ACP_SP_MAX_SITES`), every library on each, one shared budget, per-site totals and failure isolation. A "location" is read as a **site**; a site's libraries are still scanned together, as they always were. | **Closed in code and synthetic scale tests.** `tests/test_sp_scale.py` proves 30 sites × 4 libraries × 3 nested folders while bounding Graph calls. A real-tenant run remains the deployment proof. |
| Full scan, no doc-count limit at scan | Batch path for large estates; synthetic 30-site traversal is bounded by pages/folders rather than documents | **Code and synthetic proof complete.** Production proof against the customer's library sizes remains tenant-dependent. |
| Auto-flag non-applicable types (tiff, PhD, fonts…) | Filtered-by-type bucket | ✅ supported |
| Archival rule: **date-based** | `age_days` match field | ✅ supported |
| Archival rule: **folder-based** | Folder path **is read** (`parentReference`); folder-skip exists — but the disposition engine has **no path/folder match field** | **Small build** — the data is already fetched; expose a `path`/`folder` rule field. |
| Archival rule: **user-based (departed employee)** | `owner` match field | **Partial** — owner match ✅; "departed" needs the **UTSW roster** as an input (the SOW puts rule-supply on UTSW). |
| **Smart archival — check active collaborators before flagging** | Not ingested | **Gap** — needs Graph **sharing/activity signals** (permissions / recent collaborators); extra reads, possibly extra scope. |
| **Read SharePoint-native metadata** (managed metadata, content types, retention/sensitivity labels) as rule inputs | ✅ **Built 2026-09-04.** The walk expands `listItem($expand=fields)` on the page it already fetches, so content types, the tenant's managed columns, versions and check-out state arrive at no extra round trip; retention labels come from a wider `driveItem` `$select`. Every field carries an availability state, and `managed:<Column>` is a lifecycle-rule field. | **Closed as a build. Open as a PROOF**: the Graph shapes are documented-but-unverified against a real tenant. `scripts/sp_metadata_probe.py` is the instrument — run it against the UTSW tenant and read the evidence table. Sensitivity labels are the known gap: Graph exposes them on driveItem in **beta** only, so ACP reports them `unavailable`, never "unset". |
| **Tag files back into SharePoint's native columns** | Read-only. A native column write needs **`Sites.Manage.All` + per-library provisioning** — documented at `scanner.py:521` | **Out of scope by design for the pilot.** The SOW says archival is **flagging only** → ACP flags **internally** (its own store / approval queue). Native SharePoint write-back is **post-pilot** + a write scope. |
| Daily monitoring cadence | Scheduled re-scans | ✅ (1440 min) |
| **Incremental re-scan at estate scale** | ✅ **Built 2026-09-04.** A per-LIBRARY delta plan: each document library is reconstructed from its own Graph delta cursor or re-walked, in the same pass, under one budget. One expired cursor degrades one library, not the estate. | **Closed.** Its exit gate is a test, not a claim: `tests/test_sp_incremental_estate.py` runs 30 sites fully and then incrementally over the same fixture and requires identical inventories — plus zero `/children` calls for the libraries that had cursors. |
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

1. ~~**Multi-site orchestration for the 30 locations** is the real engineering item.~~ **Built
   2026-09-04** — a "location" is a site, and a site's libraries are scanned together. What is left
   is the **validation** half: no 30-site run has ever executed against a real tenant, so
   permissions at breadth, Content Type retrieval, large-library enumeration, throttling behaviour
   and SSE completion are all unproven outside unit tests. That is now the top item, not the build.
2. ~~**Native-metadata reads + folder/user rule fields** are small, high-value builds~~ — **built
   2026-09-04**. A rule can now key on content type, retention label, sharing scope, library, item
   kind, check-out state, and on the tenant's own managed columns (`managed:Records Category`).
   What UTSW still supplies is unchanged: the rule definitions and the departed-employee roster.
   What ACP still owes is the PROOF that each field arrives from their tenant — one run of
   `scripts/sp_metadata_probe.py`, which prints exactly that table.
3. **Image alt-text depends on the vision model, not the downloaded Llama.** Llama is a *text* model; WCAG
   1.1.1 needs a *vision* model, and the GPU path is currently down (backlog **R2/R12**), so image
   remediation falls to CPU/manual today. Set that expectation for the "image" half of the ~15 codes.

---

## Related backlog

- **R11** — multi-user queue isolation and concurrent fan-out are closed; `tests/test_sp_scale.py`
  adds the SharePoint-specific 30-site traversal proof. Only real-tenant breadth remains unverified.
- **R2 / R3 / R12** — RunPod vision not engaged (image alt-text degraded to CPU/manual).
- The **folder/native-metadata rule fields** and **multi-site scan** are new items this doc introduces;
  add them to `docs/BACKLOG.md` if the SOW is signed.


---

## Deployment settings this adds

- **`ACP_SP_MAX_SITES`** (default `30`) — how many SharePoint sites one scan may span. Enforced in
  three places that all read this one value: the scan route refuses a larger selection outright
  (with a message naming both counts), the walk caps itself for a job queued before that check
  existed, and `/config` serves it so the site picker stops the operator at the same number the
  server will accept. Sites past the cap are recorded as `skipped` with a reason and the estate is
  marked truncated — never dropped silently.
- **`ACP_SP_CONCURRENCY`** (default `1`, capped at 16) — how many document libraries may be
  walked at once. **Serial by default, and that is a refusal rather than caution**: overlapping
  walks dispatch a library *before* the budget that decides whether its result is wanted has been
  spent, so a scan with a tight cap walks libraries whose documents are then discarded — real
  Graph calls against a customer's tenant for an estate that is already a floor. Phase 1 rejected
  exactly that when it chose to walk libraries lazily. Raise it when the cap is comfortably above
  the estate (the ordinary scheduled 30-site run), where nothing is discarded and the win is free.
  `1` takes the identical code path, so anything reproducing at `1` is not a concurrency problem.
- **`ACP_SP_MAX_RETRIES`** (default `4`, hard-capped at 10) — how many times a **throttled or
  transiently-failed** Graph GET is retried. Small on purpose: `scanner._sp_get` is the single
  door every SharePoint call goes through — the walk, the delta feed, the site list, the drives
  list, the freshness replay — so a generous budget here multiplies across an estate rather than
  adding to it. `0` disables retrying entirely.
- **`ACP_SP_RECONCILE_DAYS`** (default `7`) — how old a library's delta cursor may get before it
  is walked in full again. A **correctness** control, not a performance knob: Graph's delta feed
  reports driveItem changes, and a managed-column edit that does not touch the driveItem may never
  appear in it, so a library synced incrementally forever could carry a stale records category
  indefinitely with nothing saying so. `0` disables the forced reconciliation for an operator who
  has measured their tenant and accepts that knowingly.
- **`ACP_SP_LIST_FIELDS`** (default `1`) — expand each item's backing `listItem` alongside the
  listing page, which is what reads content types and the tenant's managed columns. Set to `0`
  for the leanest possible walk. Turning it off does not blank those fields: it makes them report
  `unavailable` **with that reason**, so a report never presents a deliberately lean scan as an
  estate with no metadata.
- **`ACP_SP_PERMISSIONS`** (default `0`) — read each item's permissions collection. Off because it
  is one Graph call **per document** on top of the walk, which across a 30-site estate is the
  difference between a scan and an outage. Until it is on, `permissions` reports `unavailable`
  with the switch named in the reason.
- **`ACP_SP_ENUMERATE`** (default `walk`) — set to `search` to list via the SharePoint search index
  instead of walking `/children`. Faster on a very large estate and **knowingly incomplete**: the
  index is eventually consistent and under-reports recent changes with no error (issue #333
  measured 39 of 178 files on production). Not the default, and the scan logs which mode produced
  its inventory so a count can always be attributed to the method behind it.


---

## Reading a SharePoint metadata field that came back empty

Every SharePoint-native field ACP records carries a **state** beside its value, because an empty
cell has two opposite meanings and they call for opposite responses:

| State | Means | Whose problem |
|---|---|---|
| `present` | a value was read | — |
| `not_configured` | ACP read the container and the field was empty | the **tenant's** — an answer: they do not use this field |
| `unavailable` | ACP could not read the container, and the reason says why | **ACP's** — a task: a scope, a Graph version, a refused `$select` |
| `not_applicable` | the field cannot exist for this item (a OneDrive file has no site) | nobody's |

`not_configured` is only ever claimable from a container that was read successfully — enforced at
the single constructor in `api/sp_metadata.py`, not left to each call site to remember. This is
the whole safety property of the module, and `tests/test_sp_metadata.py` bite-checks it.

Where the state surfaces:

- **File drawer** — "Not read", with the reason, instead of a dash (`SharePointMetadata.jsx`).
- **Inventory CSV** — `sp_availability` and `sp_unread_reason` columns beside the values.
- **Lifecycle rule evidence** — "`retention_label` was NOT READ from SharePoint" instead of
  "`retention_label` not recorded". The rule matches nothing either way; only the human reading
  why can act on the difference.
- **`scripts/sp_metadata_probe.py`** — the per-field evidence table across a real tenant.

The one field that is `unavailable` by construction today is **sensitivity_label**: Graph exposes
`driveItem.sensitivityLabel` on **beta** and on v1.0 only through the `extractSensitivityLabels`
action, and ACP walks v1.0 driveItems. Asking for the property in a v1.0 `$select` would 400 the
whole listing for a field that would not have arrived anyway. An estate whose sensitivity labels
have never been requested must not read as an estate with no sensitivity labels — so it says so.

### Where this metadata is filterable — and where it deliberately is not

The Phase 2 plan lists "inventory filters" alongside rules, lifecycle policies, exports and audit
evidence. Four of those five are wired. The fifth has **no live host in the current product**, and
that is a recorded decision rather than an omission:

- Discover's **Document Location** filter was removed on 2026-09-02 with the per-department block
  it lived in (PRD "ACP Discover and Overview Simplification"), and nothing else on Discover
  filters the list. `discoverLocationFilter.test.jsx` pins that removal so a restored filter has
  to restore the view-only guarantee with it.
- The **review queue's** filter set lives in `DispositionReviewWorkspace.jsx`, which is currently
  unmounted (CLAUDE.md's retired-components list).

Adding a SharePoint filter to either would mean reviving a control the product deliberately took
out — the exact move CLAUDE.md warns against, and the way `RemediationFixPreview` once shipped
live because a session read *unmounted* as *unfinished*. So the metadata is filterable today
through the surfaces that exist:

- **lifecycle rules**, which are the real filter — `content_type`, `retention_label`,
  `sharing_scope`, `item_kind`, `checked_out_by`, `site_name`, `library_name`, and
  `managed:<any tenant column>`;
- **the inventory CSV**, which an auditor filters in a spreadsheet, and which carries the
  availability state beside every value so an empty cell is interpretable;
- **the file drawer**, per document.

If a filtered inventory VIEW is wanted, it is a product decision to re-open a screen that was
closed on purpose — not a gap to fill quietly from a connector phase.


---

## Incremental discovery at estate scale (Phase 3)

`_sp_whole_library_target` answers only for the one shape a single-drive delta can serve: the
whole of exactly one library. A SITE request covers several, so **every site scan fell through to
a complete re-walk on every run** — the case the incremental feature was built for, and the only
one a 30-site estate is ever in.

The plan is therefore **per library** (`core.sp_multi_sync_plan`), because a 30-site estate never
has one answer: one library's cursor is fresh, another's expired last week, a third has never been
synced, a fourth is due its periodic reconciliation. Collapsing that to a single yes/no means
either walking everything because one library needs it, or reconstructing everything and quietly
serving a stale estate for the one that did not.

```
{"delta": {drive_id: {prior_files, changed, removed_ids}},   # reconstructed
 "full":  {drive_id: "why this one has to be walked"},        # walked, with the reason
 "carried": int}                                              # documents not re-read
```

Both kinds of library go through the *same* per-item loop in `_sp_list`, so a reconstructed
library is indistinguishable downstream from a walked one — which is what makes the estate-wide
totals comparable across the two modes, and what the exit-gate test asserts.

**Uncertainty always resolves to the full listing.** No cursor, an expired link, a failed
change-check, a Graph error while resolving the libraries, a folder-narrowed request Graph's delta
query cannot honour — every one of them walks. An optimisation that can fail a scan is worse than
no optimisation, and the failure would land on the largest estates first.

**What the scope records**, because a file count cannot show that an incremental run worked (it is
supposed to equal the full run's): `scope.incremental` names the libraries reconstructed, the
libraries re-walked and why each, and how many documents were carried forward without re-reading.

### Phase 2's metadata survives a Phase 3 sync — and that needed fixing

`docs/TODO.md` P1e records the Content Type being silently erased on every delta sync for months,
because one column name was missing from one `SELECT`: `add_inventory` wrote it, and the
reconstruction baseline never read it back. Phase 2 added eleven more columns of exactly that kind,
and they are the ones lifecycle rules are written against.

They are now carried forward on the reconstructed item (`_acp_sp_carried`) and read back by
`latest_scan_inventory_items`, with `tests/test_sp_incremental_estate.py` asserting both — the
source assertion included, because the query's shape *is* the defect and a round trip would pass on
any column list that happened to include them for another reason.

The carry-forward is correct for an unchanged file by construction, and the edge worth knowing is
stated rather than glossed: a managed-column edit that does not touch the driveItem may never
surface in the delta feed, so a carried-forward column can go stale silently. That is precisely
what `ACP_SP_RECONCILE_DAYS` exists for.

### SharePoint-native freshness

`GET /scans/{sid}/source-status` used to return `untracked` for every SharePoint file, and the
reason was cost rather than oversight: Drive answers "has this drifted?" with one metadata read
**per file**, which on a 30-site estate is thousands of Graph calls to render one screen.

SharePoint has something Drive does not — a delta cursor — so the same question costs **one call
per library**. Two things make that correct rather than merely cheap:

- The replay starts from the cursor **this scan** recorded (`scope.sp_cursors`, written by
  `handlers._sp_scan_cursors` right after the plan advanced each library to "now"). The live
  cursor would answer "changed since the last sync", which becomes a different question the moment
  a second scan runs — and its answer is indistinguishable from the right one.
- The replay does **not** save the new deltaLink. Advancing it here would move the scan's recorded
  position every time somebody opened the screen, so the second viewing would report "nothing
  changed" however much had: a read that quietly destroys what it reads.

No schema change was needed — the cursors live in the scan's own scope blob, which is already
persisted per run and is already where a run records what it covered.

A file the delta mentions is `stale`, one it reports deleted is `unavailable` with
`error: deleted`, and everything else is `unchanged`. The classification is the *same*
`source_staleness` comparison Drive gets: what differs between the sources is how `current` was
obtained, not what the timestamps then mean. When the replay itself fails, the response carries
`sharepoint_freshness_error` — an operator seeing a wall of `untracked` deserves to know it is a
Graph problem this endpoint hit rather than a scan that recorded nothing.


---

## Graph throttling, and the exception report (Phase 4a)

**SharePoint had no retry at all.** Every SharePoint call goes through `scanner._sp_get`, which
made one `httpx.get` and failed on whatever came back — while the Drive path has had
`execute(num_retries=5)` from the start. Graph throttles hard, with `429` and a `Retry-After`, and
on a 30-site estate that is not an edge case; it is the ordinary Friday afternoon.

`_sp_get` now retries **429 and 5xx and transport failures**, honouring `Retry-After` when Graph
sends one (capped, because a header is caller-controlled input and a scan must not be parked for
six hours by one) and otherwise backing off exponentially **with full jitter** — not decoration:
a 30-site walk that hits a tenant-wide throttle would otherwise retry every library in lockstep,
re-creating the burst that caused the throttle at the moment the service asked for less.

**A 401/403 is never retried, and that exclusion is load-bearing.** It is a scope problem, not a
busy service: the answer will not change, Phase 1's per-site isolation reads the `PermissionError`
to mark that site blocked *with the consent that would fix it*, and retrying would turn one fast
correct diagnosis into four slow ones — delaying the only thing the operator can act on, and
dressing a permissions failure as a performance one. A 400 is not retried either: a refused
`$select` will be refused again, and the walk's tier fallback depends on it coming back promptly.

Each site records how many retries it cost (`throttled` on the site report). "This took an hour"
and "this took an hour because Graph throttled us 240 times" are the same wall-clock and
completely different problems, and only the second is one an operator can act on.

### `GET /scans/{sid}/exceptions.csv`

The exportable exception report: every site and library the scan could **not** read, with the
reason. An estate report says what was found; this says what was missed, which is the half an
auditor and an IT admin act on — and a customer chasing thirty consents needs a list they can send
to somebody rather than a screen they have to read one run at a time.

Rows are per site **and** per library, because those fail independently: a site can be readable
while one of its libraries throttles out. A site that completed is not an exception however little
it held — an empty library is an answer about the tenant, and listing it would bury the sites that
need action under the ones that are simply small. **An all-clear scan returns a header row and no
data**, never a 404: a report that 404s when nothing failed is indistinguishable from one that
could not be produced, and that difference is exactly what the reader is asking about.


---

## Walking libraries concurrently (Phase 4b)

**The trap.** `_sp_list` spends one shared budget across every selected site, and two Phase 1
properties depend on the order it is spent in: "one budget, not one per site", and "a site the
budget never reached is truncation, recorded as skipped". Consume results as they arrive and
*which* sites get skipped becomes whichever library happened to return first — the same tenant,
scanned twice, reports a different estate. A count an operator cannot reproduce is worse than a
slow scan, and a lock around the budget removes the race without removing that.

**The resolution: dispatch concurrently, consume in selection order.** A bounded look-ahead walks
up to `ACP_SP_CONCURRENCY - 1` libraries beyond the one being consumed; the budget is spent by the
consumer, in the order the operator chose their sites. The estate is identical at every
concurrency — `tests/test_sp_concurrency.py` asserts exactly that, running the same fixture at 1
and at 4 and comparing the analysis set, the inventory, the truncation flag and every per-site
status, **including the truncation boundary**, which is the half that actually depends on order.

The look-ahead is a **sliding window, not a full dispatch**: submitting every library up front
would walk all thirty of a truncated estate to use the first three, which is the cost the serial
default exists to avoid.

**Throttling is attributed per library, not per turn in the loop.** A snapshot taken around one
site's turn also catches whatever the other sites spent in parallel, which would send an operator
chasing a throttled library to the wrong site. Each walk counts its own retries on its own thread.

### Site coverage on Live Operations

A 30-site walk is one long "discovering" bar on the operations map: the file count ticks and
nothing says which sites are done, which are queued, or that one is blocked on a consent that
lapsed this morning. The per-site report is already checkpointed on the run, so the map now reads
it — "12 of 30 sites, 41 libraries · 3 not read", summed across concurrent runs because that map
is cross-tenant. A source reporting no site data (Drive, OneDrive, a scan before its first site)
shows nothing rather than "0 of 0 sites", which would be a fact about the screen.

### Still open in Phase 4

**Per-site checkpoints and resumable scans.** A 30-site scan that dies at site 28 currently
re-lists all thirty: `handlers`' existing checkpoint resume is all-or-nothing (it skips listing
only when the whole inventory was already persisted, and inventory is written *after* the listing
completes). True per-site resume means persisting each site's rows as it finishes and skipping
completed sites on retry — a streaming-inventory change to the discover path rather than a
connector change, and worth its own PR rather than being smuggled into this one.
