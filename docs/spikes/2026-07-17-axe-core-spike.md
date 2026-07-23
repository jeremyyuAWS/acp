# Spike: axe-core as a local HTML corroboration engine (ADR 0028, item C1)

**Status:** Spike complete, positive but nuanced result — axe-core is complementary to ACP's HTML rules, not a superset in either direction. Feeds the corroboration-engine framework in `docs/adr-0028-corroboration-engines` (branch, not yet merged) — written standalone so it can be folded in as an appendix without colliding with that branch's active work.

**Question:** Does porting movate-ada-web's proven axe-core integration accelerate ACP's HTML coverage?

## What was run

- Found the existing integration at `~/projects/movate-ada-web/skills/axe-assess/impl.py` — two paths behind one contract: **RECORDED** (reads a pre-captured `axe_json` fixture, fully local/deterministic, no browser) and **LIVE** (Playwright + headless Chromium + vendored `vendor/axe.min.js` injected into the rendered page, opt-in via the `[live]` extra).
- Neither Playwright nor Chromium was installed anywhere on this machine (checked both the sibling repo's own `.venv` and system Python). Installed `playwright` (40MB) + Chromium via `playwright install chromium` — a one-time, bounded cost, not a recurring dependency once cached.
- Used the LIVE path (not RECORDED) since the goal was a fresh comparison against ACP's own current fixtures, which have no pre-captured axe JSON.
- Served ACP's `test-corpus/batch-examples/*.html` (4 files: `batch0-compliant`, `batch1-critical-missing-alt`, `batch2-serious-missing-lang`, `batch3-moderate-vague-link`) over a local HTTP server, ran axe-core against each via the same Playwright invocation pattern as `impl.py`'s `_scan_live()`.
- Ran ACP's own live HTML scanner (`api/scanner.py::_analyse_html`, pure `lxml` DOM parsing — no browser, no JS execution) against the identical 4 files.

## Result: genuinely complementary, not a superset either direction

| Fixture | ACP found | axe-core found | Overlap |
|---|---|---|---|
| `batch0-compliant` | `HTML_NO_VIEWPORT_REFLOW` (1.4.10), `HTML_UNEXPANDED_ABBR` (3.1.4) | `landmark-one-main`, `region` (WCAG-adjacent best practices, no `wcagNNN` tag) | **None** — both engines found issues in the file named "compliant," on entirely different dimensions |
| `batch1-critical-missing-alt` | `HTML_IMG_MISSING_ALT` (1.1.1) + baseline's two | `image-alt` (1.1.1) + baseline's two | **1.1.1 — exact match** |
| `batch2-serious-missing-lang` | `HTML_MISSING_LANG` (3.1.1), `HTML_EMPTY_LINK` (2.4.4), `HTML_NO_VIEWPORT_REFLOW` | `html-has-lang` (3.1.1), `link-name` (tagged **both** wcag244 and wcag412) | **3.1.1 and the empty-link finding both agree** — axe's dual-tagging (2.4.4 + 4.1.2) on the empty link is arguably more complete than ACP's single 2.4.4 label |
| `batch3-moderate-vague-link` | `HTML_VAGUE_LINK` ×2 (2.4.4), `HTML_LINK_PURPOSE_AMBIGUOUS` ×2 (2.4.9), reflow | **nothing** beyond baseline landmark/region noise | **None — axe-core structurally cannot catch this** |

## The one finding worth designing around

**`batch3-moderate-vague-link.html`** is the interesting case. It's built to test vague-but-present link text ("click here," etc.) — exactly what ACP's `HTML_VAGUE_LINK` rule catches via a deny-list (`_VAGUE_LINK_TEXT` in `api/scanner.py`). axe-core's `link-name` rule only fires on **structurally absent** accessible names (empty `<a>`, no `aria-label`) — it has no opinion on text that exists but is semantically unhelpful. This isn't a bug in axe-core; it's a hard limit of DOM-structural analysis versus the vague-phrase pattern-matching ACP already does for 2.4.4/2.4.9 across every format (this is the same deny-list technique already documented in the wcag-matrix `RUBRIC` for 2.4.4 as "Machine-assisted" — generic-phrase detection is deterministic, purpose-in-context is semantic).

**Conversely**, axe-core's `landmark-one-main`/`region` findings fired on *every* fixture including the "compliant" baseline — ACP's HTML pipeline has no landmark/ARIA-region coverage at all today. That's a real, concrete gap axe-core would close on day one.

## Recommendation

**Corroborates the C1 call, with the caveat that "corroboration" here means complementary coverage, not redundant double-checking.** Concretely:
- Run both, don't replace either. axe-core adds landmark/region structure and a broader base of DOM-accessibility-tree rules (button-name, aria-* validity, etc. — not exercised by this narrow 4-file corpus but part of axe-core's standard rule set); ACP's vague-link/reflow/abbreviation checks catch things axe-core structurally cannot.
- The RECORDED path (pre-captured JSON, zero browser cost) is the right default for CI/production — reserve LIVE (Playwright + Chromium) for cases with no fixture yet, matching movate-ada-web's own existing design.
- No license or privacy concern: axe-core is MPL-2.0, runs entirely client-side in the rendered page, no external calls once the page itself is loaded (and ACP would be scanning documents it already has locally, not fetching third-party URLs).
- **Before wiring this into the 0.1 contract**: decide whether axe-core's non-WCAG-tagged findings (landmark-one-main, region — real best practices, but not one of ACP's 20 in-scope SCs) get surfaced as bonus findings without an SC key, folded into 1.3.1, or dropped — the same scope question the veraPDF spike raised for XMP metadata and font embedding. Worth resolving once, as a general policy, rather than per-engine.

## Reproduction

```bash
# one-time setup (bounded, ~40MB + browser download, then cached)
cd ~/projects/movate-ada-web && uv pip install playwright --python .venv/bin/python
.venv/bin/python -m playwright install chromium

# serve fixtures locally
cd ~/projects/acp && python3 -m http.server 8935 --directory test-corpus/batch-examples &

# run axe-core live against one, using the vendored engine + the same invocation pattern as impl.py
~/projects/movate-ada-web/.venv/bin/python - <<'PY'
from pathlib import Path
from playwright.sync_api import sync_playwright
axe_js = Path("~/projects/movate-ada-web/skills/axe-assess/vendor/axe.min.js").expanduser().read_text()
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.goto("http://localhost:8935/batch3-moderate-vague-link.html", wait_until="load")
    page.evaluate(axe_js)
    print(page.evaluate("async () => await axe.run()")["violations"])
    browser.close()
PY

# ACP's own scanner, same file
python3 -c "
import sys; sys.path.insert(0, 'api')
from scanner import _analyse_html
from pathlib import Path
print(_analyse_html(Path('test-corpus/batch-examples/batch3-moderate-vague-link.html'))['issues'])
"
```
