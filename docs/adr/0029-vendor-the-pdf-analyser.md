# ADR 0029 — Vendor the PDF analyser, as ADR 0012 did for Office

Status: Accepted
Date: 2026-07-29

## Context

ADR 0012 took ownership of the partner Office analysers: it vendored the live-path projects into
`engine/office-analysers/`, tracked in this repo, and left the full upstream solution out of tree.
The Python PDF analyser (`worker-python`) never received the same treatment. It stayed outside the
repo entirely, loaded at runtime from `ACP_PDF_ENGINE`, whose default was a developer's personal
checkout:

    api/scanner.py:22
    WP = Path(os.environ.get("ACP_PDF_ENGINE")
              or os.path.expanduser("~/projects/_review-digital-accessibility/worker-python"))

Three consequences, all of which were live on 2026-07-29.

**The engine could not be rebuilt from source control.** On that date the default path did not
exist on the machine that deploys this product. `~/projects` was gone. The only copy feeding
production images was an untracked snapshot in `deploy/public/vendor/worker-python`, gitignored,
with **0 files tracked**, of unknown age and provenance. The image running in production had been
built from it. Losing that one directory would have meant the deployed PDF engine could not be
reproduced.

**No CI runner could build the image.** The Dockerfile copied from that gitignored staging
directory, which the deploy script filled by copying from outside the repo. A GitHub Actions
checkout has neither, so the build context was incomplete by construction. This is the single
hard blocker to Chain B ever becoming a pipeline (`docs/pipeline.md`: *"Chain B is a person at a
laptop. There is no pipeline."*).

**The PDF test lane skipped everywhere except that one laptop.** Every host that lacked the path —
CI, a fresh clone, any other developer — fell back to a directory that was not there, so PDF
round-trip tests skipped rather than ran, and assertions added to them were never exercised.

The failure mode had already been paid for once: an expired ACR token turned the copy step into a
silent no-op that vendored **0 modules**, which still built, and shipped an image with no PDF
engine in it. The `>= 41` module guard in the deploy script exists because of that.

`api/scanner.py` had, in a comment, already reached this conclusion:

> Vendoring the engine the way ADR 0012 vendored the Office analysers is what actually closes this.

## Decision

1. **Vendor** the analyser into `engine/pdf-analyser/`, tracked — 41 modules across `analysers/`,
   `models/` and `remediation/`, byte-identical to the copy production was built from. This
   mirrors `engine/office-analysers/` exactly, including that neither carries its own LICENSE
   file; the standard applied here is the one ADR 0012 already set.
2. **Default `ACP_PDF_ENGINE` into the repo** (`ACP / "engine" / "pdf-analyser"`), the way
   `CLI_DLL` already defaults to the in-repo Office build. The env var still overrides, so a
   developer working against the upstream checkout is unaffected.
3. **Copy it directly in the Dockerfile** from the tracked path. The staging directory
   `deploy/public/vendor/` is no longer written by anything and stays gitignored so a stale local
   copy is never committed.
4. **Keep the module-count guard**, now against the tracked tree. It can now only fire on a
   deletion rather than a failed copy, which is cheap enough to keep.

## Consequences

A fresh clone can assess a PDF. CI can build the deploy image without access to anything outside
this repository — the precondition for Chain B becoming automated. The PDF test lane runs
wherever the suite runs, so assertions in it are exercised before CI rather than after.

The upstream `worker-python` checkout remains the place to make engine changes; this is a vendored
copy, and the same drift risk ADR 0012 accepted for the Office analysers applies here. Refreshing
it is a deliberate copy-and-commit, which is the point: the version production runs is now visible
in history rather than implied by a laptop.

This repo now contains partner-authored engine source in two places, under the same terms.
Whether that is the right commercial posture is a question for a human, not this ADR; what this
ADR records is that the posture is now *consistent* — the alternative was one engine tracked and
one engine existing solely as an untracked snapshot on a single disk.
