"""Capability gates for the two analysis engines, so skips state a true reason.

Two engines, two very different availability stories — conflating them is what let a
stale skip reason survive for weeks:

* **Office** (.NET, `AcpScan.Cli.dll`). Since ADR 0012 the analyser projects are
  vendored in `engine/office-analysers/` and the CLI builds standalone from a fresh
  clone. It is a BUILD step, not a dev-machine artifact — CI builds it
  (azure-pipelines.yml). Absent only means "nobody ran `dotnet build`".

* **PDF** (`worker-python`). NOT vendored. Loaded at runtime from `ACP_PDF_ENGINE`
  (`api/scanner.py:WP`) and lives outside this repo entirely. Its absence is a
  structural gap, not a forgotten build step.

The PDF gap bites harder than it looks: `scanner._analyse_pdf` imports `analysers`
OUTSIDE its try/except, so a missing tree raises `ModuleNotFoundError` rather than
degrading to an engine-error the way the surrounding code intends. Anything that scans
a corpus containing a PDF — or imports `remediation` — therefore hard-errors, which is
why several modules need PDF_OK even when what they assert is about Office formats.

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

PDF_ENGINE = Path(os.environ.get("ACP_PDF_ENGINE")
                  or os.path.expanduser("~/projects/_review-digital-accessibility/worker-python"))
# `analysers` backs assessment, `remediation` backs the fixers — a partial checkout that
# has one but not the other would fail confusingly mid-test, so require both.
PDF_OK: bool = (PDF_ENGINE / "analysers").is_dir() and (PDF_ENGINE / "remediation").is_dir()

NO_OFFICE = ("the .NET Office analyser CLI is not built — run "
             "`dotnet build spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj -c Release`")
NO_PDF = ("the worker-python PDF engine is unavailable: it is not vendored in this repo "
          "(unlike the Office analysers, ADR 0012). Set ACP_PDF_ENGINE to a checkout.")
