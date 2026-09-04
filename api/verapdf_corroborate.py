"""veraPDF REST corroboration engine — Phase 0 (ADR 0028, amendment local-corroboration-engines).

Two operating modes, controlled by the environment:

  RECORDED  default — CI-safe, no binary, no Docker, no network.
            parse_fixture(data) takes a pre-captured JSON dict from the verapdf/rest API
            and returns a CorroborationResult.  Tests/fixtures live in tests/fixtures/.

  LIVE      opt-in via env var ACP_VERAPDF_REST (e.g. "http://localhost:8080").
            corroborate_pdf(pdf_bytes) POSTs to the containerised verapdf/rest service
            (POST /api/validate/ua1?format=json) and returns the same CorroborationResult.

The result maps failing veraPDF clauses to the three WCAG SCs veraPDF's UA1 profile
corroborates from ACP's own detectors: 1.3.1 (tagging), 2.4.2 (page title), 3.1.1
(document language).  Out-of-WCAG-scope clauses (XMP metadata "7.1-8", font embedding
"7.21-1") are noted in `extra_clause_keys` but do not produce SC-keyed signals.

Clause-to-SC mapping is derived from spike 2026-07-17, re-confirmed 2026-07-21 against
ACP's current pipeline (docs/spikes/2026-07-17-verapdf-spike.md).  Only exact
(clause, testNumber) pairs are mapped; broader patterns are not — a new veraPDF version
adding a clause within a known section would not silently pick up the wrong SC.

Never raises for a missing or unreachable REST host — returns None instead, so callers can
treat absent corroboration as unknown rather than as a failure.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import IO

# ── clause → WCAG SC mapping ─────────────────────────────────────────────────────────────────────
# Keyed as "{clause}-{testNumber}" — the same format tests/verapdf.py's Failure.key uses.
# Sources: ISO 14289-1:2014 clause text, veraPDF UA1 profile rules, spike doc mapping table.
#
# Intentionally absent:
#   "7.1-8"  (XMP metadata stream) — PDF/UA-1 requirement, no WCAG SC equivalent
#   "7.21-1" (font embedding)      — rendering-fidelity requirement, not WCAG

_SC_MAP: dict[str, str] = {
    # 1.3.1 Info and Relationships — document structure / tagging
    "6.2-1":  "1.3.1 Info and Relationships",   # MarkInfo/Marked entry missing
    "7.1-2":  "1.3.1 Info and Relationships",   # no StructTreeRoot in document catalog
    "7.1-3":  "1.3.1 Info and Relationships",   # content items not Artifact nor tagged
    # 2.4.2 Page Titled — DisplayDocTitle viewer preference
    "7.1-11": "2.4.2 Page Titled",              # ViewerPreferences/DisplayDocTitle not true
    # 3.1.1 Language of Page — natural language
    "7.2-1":  "3.1.1 Language of Page",         # document-level Lang entry absent
    "7.2-2":  "3.1.1 Language of Page",         # content with no determinable language
}


# ── result type ───────────────────────────────────────────────────────────────────────────────────

@dataclass
class CorroborationResult:
    """Parsed output from one veraPDF REST validation run.

    `corroborated_scs` — SCs where veraPDF agrees with ACP (both found a problem).
    `extra_clause_keys` — clause keys veraPDF flagged that have no WCAG SC mapping.
    `passed_checks` / `failed_checks` — raw counts from the validationResult details.
    `compliant` — whether veraPDF found the file conformant with PDF/UA-1.
    """
    compliant: bool
    passed_checks: int
    failed_checks: int
    corroborated_scs: dict[str, int] = field(default_factory=dict)
    extra_clause_keys: list[str] = field(default_factory=list)

    @property
    def corroborates(self) -> set[str]:
        """Set of WCAG SC labels veraPDF found evidence for."""
        return set(self.corroborated_scs.keys())


# ── parser ────────────────────────────────────────────────────────────────────────────────────────

def parse_fixture(data: dict) -> CorroborationResult:
    """Parse a pre-captured veraPDF REST API JSON response.

    `data` is the parsed JSON dict from POST /api/validate/ua1?format=json.
    Handles both compliant and non-compliant results; returns an empty
    CorroborationResult (compliant=True, zero counts) for conformant files.

    KeyError / TypeError propagate on genuinely malformed fixtures — a fixture that
    silently returns empty results would hide a broken fixture from the test suite.
    """
    jobs = data["report"]["jobs"]
    if not jobs:
        return CorroborationResult(compliant=True, passed_checks=0, failed_checks=0)

    job = jobs[0]
    vr = job["validationResult"]
    details = vr.get("details") or {}
    passed = int(details.get("passedChecks") or 0)
    failed = int(details.get("failedChecks") or 0)
    compliant = bool(vr.get("compliant", False))

    corroborated: dict[str, int] = {}
    extra: list[str] = []

    for rule in vr.get("ruleSummaries") or []:
        if rule.get("status") != "FAILED":
            continue
        clause = rule.get("clause", "?")
        test_num = rule.get("testNumber", "?")
        key = f"{clause}-{test_num}"
        failed_count = int(rule.get("failedChecks") or 0)

        sc = _SC_MAP.get(key)
        if sc:
            corroborated[sc] = corroborated.get(sc, 0) + failed_count
        else:
            extra.append(key)

    return CorroborationResult(
        compliant=compliant,
        passed_checks=passed,
        failed_checks=failed,
        corroborated_scs=corroborated,
        extra_clause_keys=extra,
    )


# ── LIVE path ─────────────────────────────────────────────────────────────────────────────────────

def _verapdf_rest_host() -> str | None:
    """Return the REST host from the environment, or None if not configured."""
    return os.environ.get("ACP_VERAPDF_REST") or None


def corroborate_pdf(pdf_bytes: bytes, *, timeout: float = 60.0) -> CorroborationResult | None:
    """POST pdf_bytes to the verapdf/rest service and return a parsed result.

    Returns None when:
      - ACP_VERAPDF_REST is not set (LIVE mode not configured)
      - The host is unreachable or returns an error
      - The response body is not parseable JSON

    Never raises — callers treat None as "corroboration unavailable", not as a failure.
    """
    host = _verapdf_rest_host()
    if not host:
        return None

    url = host.rstrip("/") + "/api/validate/ua1?format=json"
    boundary = b"----ACP-VERAPDF-BOUNDARY"
    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="scan.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
        + pdf_bytes
        + b"\r\n--" + boundary + b"--\r\n"
    )
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary.decode()}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw: IO[bytes] = resp
            data = json.loads(raw.read().decode("utf-8", "replace"))
        return parse_fixture(data)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


# ── scanner integration helpers ───────────────────────────────────────────────────────────────────

# Clauses where ACP and veraPDF detect the same WCAG issue — used by the scanner to
# annotate existing findings rather than emit duplicates.
_SCANNER_RULE_TO_SC: dict[str, str] = {
    "pdf.tagged":           "1.3.1 Info and Relationships",
    "pdf.display-doc-title": "2.4.2 Page Titled",
    "pdf.document-language": "3.1.1 Language of Page",
}


def annotate_issues(issues: list[dict],
                    result: CorroborationResult | None) -> list[dict]:
    """Add veraPDF corroboration metadata to matching issues in-place.

    For each ACP issue whose WCAG SC veraPDF also flagged, attaches a
    `"corroboration"` dict: `{"engine": "veraPDF", "failed_checks": N}`.
    Issues for which veraPDF has no opinion are left unchanged.
    Returns the same list (mutated).
    """
    if result is None or not result.corroborated_scs:
        return issues
    for issue in issues:
        sc = _SCANNER_RULE_TO_SC.get(issue.get("ruleId") or "")
        if not sc:
            continue
        count = result.corroborated_scs.get(sc)
        if count is not None:
            issue["corroboration"] = {"engine": "veraPDF/ua1", "failed_checks": count}
    return issues
