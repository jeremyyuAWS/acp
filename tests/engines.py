"""Capability gates for the two analysis engines, so skips state a true reason.

Two engines, two very different availability stories — conflating them is what let a
stale skip reason survive for weeks:

* **Office** (.NET, `AcpScan.Cli.dll`). Since ADR 0012 the analyser projects are
  vendored in `engine/office-analysers/` and the CLI builds standalone from a fresh
  clone. It is a BUILD step, not a dev-machine artifact — CI builds it
  (azure-pipelines.yml). Absent only means "nobody ran `dotnet build`".

* **PDF** (`worker-python`). VENDORED in `engine/pdf-analyser/` since ADR 0029, and
  resolved from `ACP_PDF_ENGINE` (`api/scanner.py:WP`) only so anyone working against
  the upstream checkout can override it. It is pure Python — no build step — so it is
  present wherever the suite runs, which is the opposite of the Office story.

  This paragraph used to say the PDF engine was NOT vendored and "lives outside this
  repo entirely". That was true when written and false since ADR 0029, and the stale
  version cost real coverage: the first draft of the pdf ground-truth corpus recorded
  2.4.2 and 3.1.1 as unreachable work needing "tag-tree semantics or langdetect", when
  both are one pikepdf lookup in `engine/pdf-analyser/analysers/rules/pdf/`. Both are
  certification-capable pairs, and both went unverified for a commit on the strength of
  a comment. The `PDF_ENGINE` line below has carried the correction since ADR 0029;
  this header disagreed with it twelve lines later.

The PDF gap still bites harder than it looks WHEN the tree is genuinely absent (a
truncated checkout, or an override pointing somewhere empty): `scanner._analyse_pdf`
imports `analysers` OUTSIDE its try/except, so a missing tree raises `ModuleNotFoundError`
rather than degrading to an engine-error the way the surrounding code intends. Anything
that scans a corpus containing a PDF — or imports `remediation` — therefore hard-errors,
which is why several modules need PDF_OK even when what they assert is about Office
formats.

Import as `from engines import OFFICE_OK, PDF_OK` — tests/ is not a package, and pytest's
default prepend import mode puts this directory on sys.path.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_DOTNET = Path(os.environ.get("ACP_DOTNET") or os.path.expanduser("~/.dotnet/dotnet"))
_CLI_DLL = Path(os.environ.get("ACP_OFFICE_CLI")
                or ROOT / "spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll")

OFFICE_OK: bool = ((shutil.which("dotnet") is not None or _DOTNET.exists())
                   and _CLI_DLL.exists())

# Mirrors api/scanner.py's WP: the engine is vendored in-repo (ADR 0029), env-overridable for
# anyone working against the upstream checkout. This used to default to a personal path outside
# the repo, so PDF_OK was False on every host but one and ten tests skipped with a message that
# said the engine "is not vendored in this repo" — true when written, false since ADR 0029, and
# the kind of stale guard that quietly costs you a test lane.
PDF_ENGINE = Path(os.environ.get("ACP_PDF_ENGINE") or ROOT / "engine" / "pdf-analyser")
# `analysers` backs assessment, `remediation` backs the fixers — a partial checkout that
# has one but not the other would fail confusingly mid-test, so require both.
PDF_OK: bool = (PDF_ENGINE / "analysers").is_dir() and (PDF_ENGINE / "remediation").is_dir()

NO_OFFICE = ("the .NET Office analyser CLI is not built — run "
             "`dotnet build spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj -c Release`")
NO_PDF = (f"the PDF engine is missing from {PDF_ENGINE} — it is vendored in-repo (ADR 0029), so "
          "this means a truncated checkout or an ACP_PDF_ENGINE override pointing somewhere empty.")
