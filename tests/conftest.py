"""Shared test config.

Point run_scan("local") at the frozen oracle corpus (test-corpus/oracle/) instead
of test-corpus/files/ — the demo estate in files/ changes with the demo's needs
(it became the 100-file legal corpus in f442a08, silently breaking every filename
the scan regression suite asserts on), while oracle/ is the fixed set of synthetic
rule-trigger documents the assertions were written against. Regenerate them with
scripts/generate_test_corpus.py.
"""
import os
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
os.environ.setdefault("ACP_LOCAL_CORPUS", str(ACP / "test-corpus/oracle"))
sys.path.insert(0, str(ACP / "api"))


def pdf_engine_available() -> bool:
    """Is the partner PDF engine importable?

    api/remediate_pdf.py hard-imports `remediation.fixers.pdf.*` from the vendored
    worker-python tree, which scanner.WP locates via $ACP_PDF_ENGINE (defaulting to a path
    under the developer's home directory). That tree is a SEPARATE repository: it is present
    on a developer box and in the deployed image, but never on a clean CI agent — where
    remediate_pdf() raises ModuleNotFoundError and every test that drives it hard-fails.

    Tests that call remediate_pdf() therefore gate on this, exactly as ocr.is_available() and
    textchecks._langdetect_available() gate their optional dependencies. Point
    $ACP_PDF_ENGINE at a worker-python checkout to actually run them.
    """
    try:
        from scanner import WP
    except Exception:
        return False
    return (Path(WP) / "remediation" / "fixers" / "pdf" / "language_fixer.py").is_file()


# Skip (never fail) when the partner engine isn't there. A skip says "not exercised here";
# a red suite on every clean checkout says nothing at all, and trains people to ignore CI.
requires_pdf_engine = pytest.mark.skipif(
    not pdf_engine_available(),
    reason="partner PDF engine not available — set ACP_PDF_ENGINE to a worker-python checkout",
)
