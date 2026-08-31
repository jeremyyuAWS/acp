# Native-library entry points and what is actually isolated

**Status: scoping only.** This maps what exists today and what an isolation change would have to
cover. It authorises nothing, proposes no execution-model change, and does not claim the
2026-08-30 crash is understood.

**It also does not name a culprit.** `free(): invalid next size (normal)`, `free(): corrupted
unsorted chunks` and exit 139 say the heap was corrupted in *some* native allocator inside the
worker process. Nothing yet ties that to a library or a document. Several entries below are more
plausible than others; plausibility is not evidence, and the point of #1068's per-document stage
records is to replace this table's guesswork with a shortlist drawn from a real crash.

---

## 1. What the pool actually is

`api/worker.py` runs its slots as **threads in one process** (`threading`, `threading.local`; no
`multiprocessing`, no `ProcessPoolExecutor`). Production reports `pool_size: 12`.

Per-document work sits **two thread hops** below the claim:

```
worker.run_once                       (claiming thread)
└─ handlers._scan_batch
   └─ ThreadPoolExecutor.submit       hop 1   handlers.py:2767
      └─ threading.Thread(_work)      hop 2   handlers.py:2303   ← per-file timeout lives here
         └─ _analyse_and_persist_one_impl
            └─ scanner.analyse_and_assess     scanner.py:3458    ← the one-document funnel
```

`scanner.run_scan` has its own pool (`scanner.py:3837`, `_SCAN_WORKERS`) on the non-deferred path.

**Consequence:** a heap corruption in any in-process native call takes down the whole container
and every one of the ~12 in-flight documents with it — not just the document that caused it. That
is a statement about blast radius, which the code proves, not about cause, which it does not.

---

## 2. The entry points

Each row: does it cross a process boundary today, and is it bounded?

| # | Entry point | Native code | Isolated today? | Bound |
|---|---|---|---|---|
| 1 | `scanner._analyse_office` (`scanner.py:2740`) | .NET runtime, OpenXML SDK | **Yes** — `subprocess.run([DOTNET, …])` | `timeout=timeout_s`; exit code classified by `_cli_exit_reason` |
| 2 | `ocr.images_of_text` → `pytesseract` | tesseract binary | **Partly** — pytesseract shells out, so the OCR *engine* is out-of-process | `ACP_OCR_MAX_IMAGES=30`/file; images downscaled first |
| 2b | …the Pillow decode feeding it (`api/ocr.py:112`) | **libjpeg / libpng / zlib, in-process** | **No** | resize cap only |
| 3 | `scanner._analyse_pdf` (`scanner.py:2568`) | **pikepdf → libqpdf; pdfplumber → pdfminer.six; pypdf** | **No** | none of its own |
| 4 | `office_structure.checks_for` | **lxml → libxml2** (OOXML parts), pikepdf for PDF contrast | **No** | none |
| 5 | `pii.extract_text` / `textchecks.content_findings` | **pikepdf / pdfminer / lxml**, `langdetect` (pure Python) | **No** | none |
| 6 | `render._render_pdf_page` (`render.py:117`) | **pypdfium2 → PDFium, in-process** | **No** | none |
| 7 | `render` office→PDF (`render.py:106`) | LibreOffice | **Yes** — `subprocess.run([soffice, …])` | `ACP_OFFICE_RENDER_TIMEOUT=60` |
| 8 | `report_tagged` (`report_tagged.py:538`) | Chromium | **Yes** — `subprocess.run([_CHROMIUM, …])` | `timeout=45` |
| 9 | `store` / `psycopg2` | libpq | **No** | pool-level only |

**Correction to something I said earlier in this workstream:** I claimed the .NET analyser was the
*only* out-of-process boundary. That was wrong — there are three (`#1`, `#7`, `#8`), plus
tesseract's own (`#2`). What is true is narrower and still the point: **the document-parsing path
that runs on every file — rows 3, 4, 5, and the decode half of 2 — is entirely in-process.**

Rows 6–8 are worth separating from the rest: `#7` and `#8` are already isolated, and `#6`/`#7`/`#8`
are reached from `routes/scans.py` (preview, render-verify, report export), **not** from
`analyse_and_assess`. They are not on the per-document scan path that was running when the crash
happened.

---

## 3. What bounds exist now

- **Per file:** `ACP_SCAN_FILE_TIMEOUT_S=600` (`handlers.py:2285`), enforced by `th.join(cap)`.
  It does **not** kill the thread — the comment says so: the stuck thread is left to exit on its
  own via its sub-calls' own bounds. A wedged native call therefore keeps its OS thread and its
  memory for as long as it likes.
- **Per subprocess:** rows 1, 7, 8 each have their own timeout. Row 2's tesseract call does not.
- **Per job:** `ACP_JOB_MAX_LEASE_S=3600` stops lease extension, letting the sweeper reclaim.
- **Retry:** `job_retry_policy` + `max_attempts`. **There is no per-document poison guard** — a
  document that crashes the worker is re-claimed after the lease lapses and can crash it again.
  `db40880c03de4b89` reached attempts-exhausted this way, which is the queue behaving as designed.
  Whether a single document drove the three restarts is a HYPOTHESIS, not a finding: nothing
  available correlates a document with a restart, and an earlier draft of this section asserted
  it anyway — the same overreach the header warns against, two sections later. What the retry
  path establishes is only that a crashing document *would* be re-claimed and could crash the
  worker again; establishing that it *did* needs the correlated records #1068 now emits.

---

## 4. What an isolation change would have to cover

Not authorised; listed so the size is visible before anyone starts.

1. **Boundary placement.** The natural seam is `analyse_and_assess` — one document in, one result
   dict out, already the funnel #1068 instruments. Moving it out-of-process means the child needs
   the file, the rubric, and the scan id, and returns JSON. It does **not** need Drive tokens.
2. **Bounded concurrency.** Child processes multiply memory by pool size; 12 concurrent PDF
   parsers is a different memory profile from 12 threads sharing one heap.
3. **Timeouts** at the child, and a real kill — `subprocess` timeouts terminate, unlike the
   current `th.join(cap)` which does not.
4. **Memory limits** per child (`RLIMIT_AS` / cgroup), so one document cannot exhaust the node.
5. **Child cleanup** on worker shutdown, cancellation, and crash — orphaned children after a
   SIGSEGV are a second failure mode.
6. **Cancellation** must still reach the child: `worker.check_cancel()` reads a thread-local, and
   a child process does not inherit it.
7. **Poison-document guard**: after N crashes attributable to the same `doc`, dead-letter it
   instead of re-claiming. This needs #1068's records to identify the document at all.
8. **Cost.** A process per document adds startup and IPC to every file in an estate scan. Whether
   that is acceptable is a product decision, not a technical one.

---

## 5. What would actually identify the culprit

The map narrows candidates; it does not close the question. What would:

- **#1068's stage records from a real crash.** A document with `stage.enter` and no matching exit,
  across more than one crash, is the first real evidence. One crash gives ~12 candidates.
- **A core dump or `faulthandler`**, which would name the C frame directly. Neither is enabled.
  `faulthandler.enable()` writes a Python traceback on SIGSEGV to stderr — cheap, and it is the
  single highest-value addition here. Not done: it is a code change, and this document is scoping.
- **Reproduction in staging** against the shortlist, once there is one.
