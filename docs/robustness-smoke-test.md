# Robustness smoke test — large & malformed files

**Goal: robustness, not accuracy.** This test proves ACP **degrades honestly** on large and malformed
files — no crash, no hang, no silent drop, every truncation/cap surfaced — *not* that a 120-page file
scores perfectly. It deliberately pushes past ACP's known bounds and checks the platform reports the
limit instead of hiding it.

## Generate the corpus

```bash
pip install fpdf2 pypdf Pillow python-docx python-pptx openpyxl
python scripts/robustness_corpus.py --out ./robustness-corpus        # full size
python scripts/robustness_corpus.py --out ./robustness-corpus --scale 0.15   # quick, small files
```

This writes ~14 files plus **`manifest.json`** — the expected result for every file (Discovery bucket,
counted known defects, which caps should trip, robustness assertions, and byte size on disk).

## What's in the corpus and what each file stresses

| File | Stresses | Expected bucket |
|---|---|---|
| `pdf-text-120p.pdf` | parse throughput; **reading-order samples only the first 20 pages** — the tail must be surfaced as unassessed | assessable-remediable |
| `pdf-scanned-100img.pdf` | **OCR image cap (30/file)** → `OCR_IMAGE_CAP_REACHED` must appear | assessable, assess-only |
| `pdf-50images.pdf` | **vision figure cap (25)** + OCR cap; alt-text at volume (CPU/manual while RunPod is down) | assessable-remediable |
| `locked-password.pdf` | password-protected → must fail **closed** into unreadable | unreadable |
| `corrupt-truncated.pdf` | half a PDF (no trailer/xref) → parser exception path | unreadable |
| `docx-150p-images-tables.docx` | **.NET 180s CLI timeout** risk; images w/o alt, tables w/o headers | assessable-remediable |
| `docx-500-tiny-images.docx` | pathological image count — memory / OCR cap | assessable-remediable |
| `zero-byte.docx` | 0 bytes → fail closed | unreadable |
| `wrong-ext.docx` | PDF bytes with a `.docx` name → OpenXml open must fail closed, not misassess | unreadable |
| `pptx-100slides.pptx` | **.NET timeout** on a 100-slide deck; titleless slides + undescribed images | assessable-remediable |
| `xlsx-30sheets-100kcells.xlsx` | **.NET timeout / memory** on a big workbook | assessable-remediable |
| `empty-workbook.xlsx` | `BlankWorksheetRule` (1.3.2) **and** the Trivial (ROT) triage path | trivial-candidate |
| `image-not-document.png` | reconciling **filtered-by-type** bucket | filtered-by-type |
| `control-clean.docx` | baseline — if THIS misbehaves, the problem isn't scale | assessable-remediable |

(Sizes scale with `--scale`; the page/slide/cell counts in the filenames are the `--scale 1.0` targets.)

## Run it against ACP

The generator only makes the files + expected manifest; **running the scan needs a live backend** (the
full Python + .NET + OCR stack — it can't run against the vite preview, which serves the shared checkout).
So: upload the corpus into the connected source (Drive/SharePoint), run a Discover + Assess pass, then
compare the result to `manifest.json`.

## Pass/fail — the robustness assertions

A run **passes** only if ALL of these hold. These are about *honesty under load*, not scores.

1. **No crash / no hang.** Every file's scan terminates or is honestly reclaimed by the sweeper. No
   worker crash, no job stuck `running` past its lease, no double-processing.
2. **Counts reconcile.** Every file lands in **exactly one** Discovery bucket, and the bucket counts sum
   to the file total. `manifest.json`'s `buckets_present` is the reference.
3. **Truncation is surfaced, never hidden.** The image-heavy and scanned files must show the cap
   (`OCR_IMAGE_CAP_REACHED`, ≤25 figures, first-20-pages reading order) — a partially-assessed file must
   *say so*, never report a silent clean pass.
4. **Timeouts → "uncertain," not fake-pass.** If the .NET CLI times out on the 100-slide / 100k-cell /
   150-page file, that file must be marked **uncertain** (score = upper bound, not certifiable) — never a
   crash and never a fabricated pass.
5. **Unreadable ≠ passing.** `locked-password.pdf`, `corrupt-truncated.pdf`, `zero-byte.docx`,
   `wrong-ext.docx` must all land in **unreadable** with a reason. None may be scored as compliant.
6. **Known defects are all reported.** For each assessable file, every SC in `known_defects` must appear
   in the findings (counts may differ where a cap truncated — but then assertion #3 must hold).
7. **Wall-clock / memory recorded.** Capture per-file scan time and peak memory to find where ACP
   degrades. The pilot caps at ~25 pages (`docs/pilot-scope.md`); this test's job is to locate the real
   ceiling *above* that and confirm the degradation is graceful.

## Interpreting a failure

- File scored **clean** but had counted defects → a **silent drop** (worst case — fix first).
- File **crashed the worker** or left a **stuck job** → durability bug (job lease / sweeper).
- Timeout produced a **pass** instead of **uncertain** → the honesty contract is broken.
- Unreadable file scored as **passing** → fail-closed is broken.
- A cap tripped with **no surfaced marker** → truncation is hidden (assertion #3).

Note: with **RunPod vision down (R12)**, every alt-text result here is CPU/manual — so the image files
test the *fallback path's* robustness, not GPU throughput. Re-run after R2/R3 to test the GPU path.
