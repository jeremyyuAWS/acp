# App styling audit — September 12 follow-up

The audit uses an isolated Vite server rooted in the owned worktree. It renders the actual progress summary, finding tiles and queue drawer with production CSS. It never uses the shared preview server or customer credentials. A second isolated fixture mounts actual Sources, Discover, Assess, Live Operations, Scan Analytics and Conformance screen components with deterministic telemetry. Publication also uses the existing isolated real Publish component fixture. Its obsolete pre-batch button labels were updated to current behavior; authorization checks remain unchanged.

## Completed fixes

- Queue drawer file/status headings wrap without sacrificing the filename. Long filenames, reasons and status labels stay within the drawer. The original production styles reproduced content overflow at 1280px in the new browser fixture.
- Discover site-picker actions wrap on narrow layouts. Actual Sources connected-card actions wrap at narrow widths; the populated SharePoint fixture originally overflowed by 101px at 390px.
- Discover breakdown panels shrink below chart-label min-content widths; the actual empty Discover screen originally overflowed by 7px at 320px. Analytics auto-fit grids bound their 300px minimum to the container; the actual empty Analytics screen originally overflowed by 8px at 320px.
- Publication detail labels and values share bounded grid columns and wrap safely.
- Remediate and Release tiles switch to one column at 420px; counters and transient signed deltas can wrap rather than disappear into clipped tiles. The compact Assess surfaces, font hierarchy and semantic labels are retained.
- Finding/publication tiles pass execution-bound React keys directly, removing the browser warning while preserving reset behavior between runs. Live Operations uses React Flow’s registered default Bezier edge name, preserving the existing curvature.

## Audit matrix

| Area | Evidence | Result |
|---|---|---|
| Sources | Actual Integrations screen: empty connections and populated SharePoint connection, production CSS at 1280/640/390/320px | Pass; connected-card actions wrap, no page overflow |
| Primary workflow navigation | Production navigation CSS at the same widths | Pass; horizontal navigation scroll stays inside its container |
| Discover | Actual Discover screen: empty and populated document inventory at all four widths; production picker and breakdown styles | Pass; actions and chart totals reflow, no page overflow |
| Assess | Actual AssessSummary with a recorded finding and selected criterion at all four widths | Pass; compact KPI cards and results reflow |
| Live Operations | Actual AdminLiveTraffic with unavailable capacity/no active work at all four widths | Pass; status/KPI/map container stays within page; interactive graph has its own pan/zoom |
| Scan Analytics | Actual AdminInsights with no completed scans at all four widths | Pass; grid reflows with bounded column minimum |
| Conformance | Actual AcrWorkspace with no reports at all four widths | Pass; setup and export-assurance cards reflow |
| Assess / Remediate shared table | Actual production file-table and header styles, 25 long-name rows, horizontal and vertical scroll | Pass; header surface stays opaque, filename and header retain the same UI font |
| Remediate / Release KPI layout | Actual progress summary and outcome components, six-digit count, live +100,000 update delta and narrow layouts | Pass; tile content stays within bounds |
| Queue drawer | Actual component, long name/reason/status, keyboard Tab loop, Escape and opener focus restoration | Pass at all four widths |
| Reduced motion | Browser media emulation, actual drawer animation computed style | Pass; drawer animation is disabled |
| Publication | Existing `release-layout.fixture.mjs`, real Publish component with deterministic API fixtures | Pass at 1280/390/320px; default batch, zero-ready actions, optional proposal disclosure and exact server-plan authorization covered |
| Filenames / technical metadata / Operations typography | Existing DOM and typography regression tests | Pass; 32 focused component/typography/activity tests across 10 files, plus production build |

640 CSS px represents the layout viewport of a 1280px browser at 200% zoom. This verifies reflow at that effective width; it does not claim a native browser-menu zoom or every operating-system font rendering was inspected. Sources, Assess, Operations, Analytics and Conformance screenshots were visually reviewed at narrow/effective zoom widths. The fixture includes adversarial filenames longer than typical customer names.

Screenshots: [320px narrow drawer](qa/app-styling/narrow-320.png), [640px effective zoom layout](qa/app-styling/effective-zoom-640.png).

## Reproduce

From the owned worktree's `frontend` directory:

```sh
node e2e/app-styling.fixture.mjs
node e2e/app-panels-styling.fixture.mjs
node e2e/release-layout.fixture.mjs
```

The new fixture fails on page overflow, clipped KPI/picker/detail content, drawer overflow, inconsistent table fonts, transparent sticky headers, broken keyboard behavior, motion preference violations or page errors. Its CSS assertions run in a real Chromium browser, not a layout-free DOM emulator. Browser binaries can use the established `ACP_E2E_CHROMIUM` override.

Legacy retired panels, every possible loaded report/analytics dataset or loading/error state, native Office/PDF rendering and customer SharePoint permissions are outside this styling fixture. They must not be marked verified solely from these checks.

## Latest Review and supporting-report behavior

The live Review action row now contains only the auto-apply AI switch and feedback. Ready-apply, run-readiness and publication buttons are deliberately unmounted there; legacy approval code is retained. A green, dismissible toast appears only after the server confirms a successful enable: “AI reviews will be automatically approved.” It explicitly says manual work remains in Review. Initial loading of an already enabled setting, failed/uncertain save responses and stale run responses do not produce a success toast.

New source-anchored PDF heading/header proposals display friendly read-only summaries, preserve executable JSON behind Technical plan, preserve exact approved values and source/proposal versions, and receive no AI-draft credit. Invalid structural plans cannot enter bulk readiness. Native Word tracked-change companions and JSON evidence attach only to the exact delivered file/digest/release; native assets do not trigger Generate PDF reports. These paths have focused DOM/action regression coverage, not a claim that every Review or Conformance production dataset was visually exercised.
