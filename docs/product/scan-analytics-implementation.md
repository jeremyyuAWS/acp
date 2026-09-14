# Scan Analytics implementation

The former sequential lifecycle funnel is deliberately unmounted because its review and assessment populations overlap. Its retained implementation and orphan test make that decision reversible.

The first release implements cross-user platform reporting using existing recorded scan data. The detailed product direction is in [the PRD](scan-analytics-prd.md).

## Included

- All retained scan attempts, including running, failed, interrupted, cancelled, and superseded states.
- User, source, status/outcome group, search, period, and custom UTC date filters with URL persistence.
- Separate start-time activity and completion-time successful-result populations, each with a paginated register.
- Summary cards with contributor drill-down; daily stacked activity scaled by volume, outcome rankings, source activity and result charts, user activity, and a fixed 0–100% result-rate chart with missing-value gaps.
- Equivalent accessible chart tables, keyboard controls, explicit unknown values, stale/error/loading states, and partial-data notices.
- Read-only scan detail with recorded stage events, document observations, document-type and WCAG criterion-instance charts, and finding drill-down.
- CSV exports of the selected register population across all pages, a companion methodology download, safe spreadsheet text handling, audit logging, and cache prevention.
- Existing platform-admin enforcement on every reporting endpoint plus analytics workspace capability mapping. Local development without configured ownership retains the existing development-mode behavior.

## Definitions and limits

This deployment's administrator scope is platform-wide across owner-email tenants. It does not have a recorded organization boundary for these scans. Standard users cannot obtain these cross-user projections when administrator authentication is configured.

Document totals are scan observations and repeat on rescans. Successful-completion rates use recorded file counters; the separately valid eligibility denominator is not available in this register. The screen discloses this and does not claim estate coverage, unique files, or verified WCAG conformance. Mean scan scores equally weight recorded scan averages.

Current review backlog is explicitly a platform snapshot unaffected by reporting filters. Undated attempts remain inspectable in all-time results but cannot be placed on dated charts. Missing or inconsistent result counters are excluded with a visible count.

Data-through means the latest recorded run start/end, rather than ingestion freshness. Overview, CSV, and methodology are independently generated; compare their timestamps if records change between requests. Scan detail returns the first 100 recorded events with a visible limit note. File type and criterion charts describe the selected scan's recorded observations and finding instances, not deduplicated historical issues.

The backend paginates responses but currently reads retained run aggregates to build the overview. The PRD's 100,000-run latency targets have not been benchmarked. Long histories can also produce long chart tables; database aggregation and time bucketing remain scale work.

## Remaining PRD phases

Organization-specific access, stable file deduplication, department/source-connection breakdowns, categorized exception causes, historical finding aging, verified remediation/release trends, matched-file cohorts, saved views, report exports, and anomaly notifications require additional recorded data or product decisions. The dashboard explains unavailable dimensions instead of displaying empty coming-soon charts.

## Verification

Validation is performed against this isolated worktree using backend fixtures and frontend DOM tests. The shared preview server is not evidence for this branch. Axe verifies DOM semantics under jsdom; visual color contrast and manual screen-reader testing remain separate checks.
