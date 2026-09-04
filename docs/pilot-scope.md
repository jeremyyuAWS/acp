# ACP pilot — scope & limitations

**Audience:** the pilot customer (hospital IT + the 3 pilot users) and the mova.io team.
**Purpose:** set honest, explicit boundaries so the pilot demonstrates what ACP does *well* and never
implies capability it doesn't have. Each limit names the backlog item it traces to, so it can be
re-checked and lifted as the platform matures. Where this doc and the code disagree, the code wins.

---

## Agreed pilot parameters

| Dimension | Pilot scope |
|---|---|
| Users | 3 pilot users |
| Source | **SharePoint** (read-only, delegated, single tenant) — selected sites and their document libraries, up to 30 sites per run |
| Document types | **DOCX (primary)**; XLSX / PPTX / PDF *assess-only* (see below) |
| Content | **Text + images only** — no audio/video |
| Language | **English only** |
| Size | **≤ ~25 pages / file** |
| Data | **PII / PHI** — everything stays local / in-tenant |

---

## Hard limits — impose these, or the pilot misleads

1. **DOCX = full remediation; PDF / XLSX / PPTX = assess + assisted/human, not one-click fixes.**
   DOCX is the mature format (most criteria auto-fix, re-scan verified). PDF auto-fixes some criteria
   (language, title, contrast, bookmarks) but **2.4.4** is human-only (no link write-back), **4.1.2** is
   AcroForm-only, and there's no re-tagging or table-`/TH` fix. XLSX/PPTX still have ~12 not-ready cells.
   *Promise remediation for DOCX; promise assessment (plus assisted/human fixes) for the rest.*
   — traces to **R8** (capability completion).

2. **Image alt-text (1.1.1) is human-reviewed, not auto-generated.**
   GPU vision is **not engaged in production** — image alt-text falls back to a filename-guess template
   routed to manual authoring. Either **fix this before the pilot** or scope image-light documents and
   tell users alt-text is human-in-the-loop. The per-fix **🟢 Local / 🟡 Cloud** badge is the honest tell.
   — traces to **R2 / R3 / R12** (RunPod vision) and **W6** (provenance badge, shipped).

3. **No multimedia.** ACP has no speech-to-text / captioning pipeline — audio/video can only be *flagged*,
   never captioned. Exclude `.mp4 / .mov / .webm / .mp3 / .m4a / .wav` from scope entirely.
   — traces to `docs/loe-multimedia-captioning.md` (not built; ~10–14 pw for Phase 1).

4. **English only.** OCR and the local models are English-oriented; non-English content degrades silently.

5. **PHI → AI stays local; no cloud AI providers.** In the default config nothing leaves the network
   (local Ollama). Do **not** enable a cloud provider for the pilot; rely on the 🟢/🟡 provenance badge to
   prove locality per fix. Confirm the vision path is local before any PHI doc is scanned.

6. **No write-back to source.** SharePoint access is read-only — remediated files are delivered as
   **downloads**, not written back into SharePoint. Users must expect a "download the fixed copy" flow.

---

## Soft caps — scope & performance

7. **≤ ~25 pages / file.** Aligns with real pipeline bounds: OCR caps at **30 images/file**, vision at
   **25 figures/file**, PDF reading-order samples the **first 20 pages**. Beyond that, coverage truncates
   (surfaced honestly, but the file is only partially assessed).

8. **Selected SharePoint sites, with an explicit boundary.** A run can span up to 30 selected sites
   and walks every document library on each. The 30-site path and concurrent queue isolation are
   synthetically verified; until the tenant is available, library sizes, permissions and Graph
   throttling at UTSW remain unmeasured. The UI records every selected site and library so omissions
   are visible rather than silently treated as a complete estate.

9. **Continuous Monitoring is change-based only.** The Monitor tab now surfaces real source drift, but
   re-validation triggers on source *change*, not on a schedule/age. Don't promise time-based re-attestation.
   — traces to **R5** (shipped) and **W9** (time-based re-validation, not built).

---

## Pre-pilot checklist (confirm before the first scan)

- [ ] **Deployed build is current** — `/healthz` shows the intended version (not just "PRs merged"; the
      deploy has a chronic wedged-Actions pattern — verify the version string).
- [ ] **SharePoint app registration done** — single-tenant, SPA redirect URI, the three delegated read
      scopes (`User.Read`, `Files.Read.All`, `Sites.Read.All`), **admin consent granted**, no client
      secret. See `docs/sharepoint-app-registration.md`.
- [ ] **AI is local** — no cloud provider enabled; provenance badge reads 🟢 Local on a test fix.
- [ ] **Scope set** — the approved SharePoint sites selected (up to 30), DOCX-led, English,
      ≤25 pages per document, media excluded.
- [ ] **Expectations set with users** — DOCX gets fixed; other formats get assessed; alt-text is
      reviewed; output is a download.

---

## One-line summary for the customer

> The pilot fixes and certifies **English DOCX documents (≤25 pages) from selected SharePoint sites**,
> assesses PDF/XLSX/PPTX, keeps all PHI on your own infrastructure, and delivers remediated files as
> downloads. Image alt-text and non-DOCX fixes are reviewed by a person; audio/video and non-English
> content are out of scope for this pilot.
