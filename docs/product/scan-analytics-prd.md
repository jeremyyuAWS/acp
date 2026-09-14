# PRD: Transparent cross-user Scan Analytics

Draft for product review · September 14, 2026 · Mova iO Accessibility Platform

## Outcome

An authorized administrator can answer: **Who scanned what, when, what happened, what needs attention, and which evidence supports each number?** Every aggregate must explain its population and calculation and lead to its underlying records.

“All users” means users within the viewer’s authorized organization. Tenant isolation must be verified before expanding reporting access.

## Current experience review

The supplied screenshot shows Discover, not Scan Analytics. This review examined fetched origin/main at commit 98e3ad0f; it did not exercise production data or runtime behavior.

| Observed implementation | Required improvement |
|---|---|
| Admin overview queries across users and enforces admin access. | Show organization, authorized user scope, represented users, and reporting freshness. Verify tenant boundaries. |
| “Unique files” sums file counts across scans. | Rename to document observations until stable file identity supports genuine deduplication. |
| Query requires completed_at and excludes superseded runs. | Include all scan attempts; show running, failed, interrupted, cancelled, and superseded outcomes explicitly. |
| Trend badge measures average score; graph plots certifiable rate. | Pair each badge with the same named metric. |
| Graph spaces scans evenly and renders missing percentages as zero. | Use real timestamps, labeled axes, a fixed 0–100% rate scale, and gaps for unavailable data. |
| Scope, Compare, Rubric, and Export are disabled. | Deliver working controls and explain unavailable dimensions. |
| Pending review is fetched separately without selected source/period filters in this route. | Label it as a current snapshot or apply compatible filters explicitly. |
| Average score equally weights scan averages. | Disclose weighting; use document scores when available. |
| Recent scans stop at 20 rows without drill-down or pagination. | Provide a full searchable register with explicit statuses and evidence navigation. |
| File types, backlog aging, and remediation are placeholders. | Release only when backed by recorded metadata and events. |
| Lifecycle visual places review after certifiability. | Verify population relationships; avoid a funnel when stages overlap. |

Code reviewed: frontend/src/AdminInsights.jsx; api/routes/analytics.py; api/analytics_trends.py; api/store.py.

## Users

- Organization administrator: reconcile activity and investigate users or failed scans.
- Accessibility lead: prioritize unresolved findings and distinguish eligibility from verified outcomes.
- Department manager: inspect authorized departmental results.
- Auditor: trace metrics to dated evidence and export reporting context.

Access rules must apply to aggregates, filter options, details, evidence, and exports. Standard users receive only explicitly authorized views.

## Proposed layout

1. Reporting context: organization, user scope, date range, timezone, refreshed-at, data-through, and partial-data warnings.
2. Filters: custom dates, user, department, source connection, connector type, status, file type, and rubric/version. Active chips, clear-all, and shareable URL.
3. KPI cards: attempts, successful runs, unsuccessful runs, active scanning users, assessment observations, and certifiable rate. Each opens its contributing records.
4. Core charts with accessible tables and exact denominators.
5. Searchable scan register with pagination and scan detail.
6. Metric definitions, data limitations, and export.

Keep the overview readable; use expandable sections for deeper distributions. Follow the existing visual style.

## Charts and drill-downs

| Chart | Purpose and representation | Selection opens | Phase |
|---|---|---|---|
| Scan activity | Daily/weekly stacked bars by terminal outcome; current running scans shown separately. | Date/status-filtered runs | P0 |
| Assessment results over time | Aligned observation-count and certifiable-rate charts with real time axes. | Contributing scans and observations | P0 |
| Source/department outcomes | Horizontal stacked bars with counts, rates, and Unknown buckets. | Matching runs/documents | P0 |
| User activity | Ranked bars plus attempts, successes, errors, and last activity table. | User history, then scan detail | P0 |
| Exception reasons | Ranked recorded error categories, including unclassified. | Runs and authorized diagnostics | P0 |
| File types | Supported, unsupported, assessed, and processing-error distributions. | Document observations | P1 |
| Finding severity and WCAG criteria | Severity bars and criterion ranking with rubric context. | Findings and evidence | P1 |
| Backlog aging | 0–7, 8–30, 31–60, 61–90, >90 days, and unknown age. | Open findings and ownership | P1 |
| Remediation and verification | Recorded attempts, usable outputs, verification outcomes, review, and release. | Execution and verification evidence | P1 |
| Matched-file improvement | Before/after results for comparable identities and rubrics. | Matched cohort and historical evidence | P2 |

Every chart requires units, axis labels, legends, exact-value tooltips, sample sizes, exclusions, keyboard interaction, and an equivalent data table. Color cannot be the only status cue. Missing data is unavailable, never a measured zero.

## Metric dictionary

| Metric | Contract |
|---|---|
| Scan attempts | Distinct run IDs started within the selected interval, across authorized users; all recorded statuses included. |
| Successful runs | Attempts with a recorded successful terminal outcome; document the mapping from actual statuses. |
| Assessment results | Outcomes completed within the interval. Label this completion-time basis separately from attempt activity. |
| Active scanning users | Distinct initiating actors; unknown actor remains a separate bucket. |
| Assessment observations | Distinct scan/document observations; rescans count again. |
| Unique files | Distinct stable source/file identities; disclose unresolved identities and deduplication limits. Never deduplicate by filename alone. |
| Certifiable rate | Certifiable assessed observations / observations with a valid eligibility result. Show excluded unsupported, processing-error, and missing outcomes. Automated eligibility does not establish conformance. |
| Average score | Mean valid document score with sample size; if only scan averages exist, label “Mean scan score” and disclose equal weighting. |
| Open findings | Distinct unresolved finding identities as of the reporting timestamp; do not derive from files minus certifiable files. |
| Processing error rate | Recorded processing-error observations / attempted observations, with unknown outcomes disclosed. |
| Pending review | Current authorized queue snapshot with explicit as-of time and filter scope. |
| Change | Rate changes in percentage points; count changes absolute and relative. Zero baseline means no comparable baseline. |

Use start-inclusive/end-exclusive timestamps and an explicit reporting timezone. Keep historical activity, current backlog, and latest-known estate snapshots distinct. Scans across all users do not prove coverage of every estate file.

## Detail experience

Overview → chart segment → filtered register → scan → document observation → finding/evidence.

Register columns: run ID, initiating actor, department at run time when recorded, source connection, start/end, duration, status, document outcomes, errors, rubric/version, and evidence availability. Provide server-side search, stable sorting, and pagination.

Scan detail shows recorded stage history, partial results, stop/failure reasons, document outcomes, and existing assessment/remediation evidence. Preserve filters and breadcrumbs. Recheck authorization at every detail request. Do not equate the initiator with the file owner or remediation assignee.

## Data and transparency

Verify or add organization ID, stable actor ID, source/file identity, document/version identity, run and stage events, terminal outcomes, rubric version, assessment observations, finding identities, resolution events, remediation events, verification events, and timestamps.

Responses and exports include scope, filters, timezone, time basis, generated-at, data-through, metric version, exclusions, unavailable fields, retention boundary, and partial-result state. Historical backfill uses recorded evidence only; do not invent past departments, finding ages, or verification outcomes. Display coverage start dates for newly collected fields.

Distinguish no matching scans, missing metadata, load failure, partial data, and stale retained results. Unknown buckets participate in totals. Unavailable denominators produce no percentage.

## Comparison and export

P0 compares the preceding equal-length period with identical filters and exact interval labels. Show sample sizes and composition changes; period differences alone do not prove remediation impact. P2 supports comparable matched-file cohorts.

P0 exports all filtered authorized register rows as CSV with a companion methodology file. P1 adds chart tables and a readable report. State whether an export includes all rows or only a page. Preserve unavailable values and audit actor, time, scope, and outcome under existing policy.

## Acceptance criteria

- Multi-user fixtures reconcile all eligible run IDs exactly once, including active and failed runs. Other tenants are excluded from APIs, aggregates, details, and exports.
- Direct requests and altered IDs cannot bypass standard-user permissions.
- Three scans of one identified file produce three observations and one unique file; unresolved identities are visible.
- Chart selections, tables, and exports reconcile under the same reporting snapshot.
- Paired trend graphs and badges use the same metric; missing points never plot as zero and rate axes stay 0–100%.
- Timezone, daylight-saving, and exact interval boundary fixtures pass.
- Review snapshot scope is explicit; unsupported/unassessed files cannot appear as passed.
- Runs beyond the first 20 are searchable and pageable; drill-down preserves filters.
- Keyboard navigation, screen-reader tables, visible focus, and non-color cues meet WCAG 2.1 AA through automated and manual verification.

## Delivery and success measures

**P0:** trustworthy definitions, verified access scope, all run statuses, working filters, five core charts, full register, evidence navigation, comparison, and CSV export.

**P1:** file types, findings, aging, remediation/verification evidence, saved views, and report export. Gate each feature on available recorded evidence.

**P2:** matched cohorts, latest-known estate reporting with freshness rules, and approved anomaly notifications.

Proposed performance targets to validate: overview p95 below 2 seconds and first detail page below 1 second at 100,000 runs; large exports asynchronous. Require exact fixture reconciliation and zero unauthorized records. In usability testing, 90% of administrators should find a user's failed scan and explain a denominator within two minutes. Measure drill-down completion, filter use, export success, and abandonment.

## Decisions before implementation

1. Confirm tenant boundaries and whether an analytics-reader permission should supplement admin access.
2. Confirm stable file identities, retention, and backfill limits.
3. Approve certifiability terminology and denominator with the accessibility owner.
4. Decide whether latest-known estate reporting is required in addition to scan activity.
5. Verify event coverage for findings, resolution, verification, and department history before setting P1 dates.

This document proposes behavior; it changes no application code and does not assert production support for the proposed data model.
