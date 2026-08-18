"""Core-17 WCAG code-set catalog + eligibility preview (read-only).

Phase C2 of the Discover/Assess Lifecycle PRD. Assess lets a user pick a set of WCAG
Success Criteria to assess and see how many files are eligible BEFORE starting a run.

A product decision fixed the selectable set to the canonical Core 17
(`assessment_policy.MOVA_TRACKED`). The "15" some docs cite is only the docx-format
projection of these 17, so nothing here hardcodes a separate list of 15.

This module is a thin, READ-ONLY projection over the tables that already live in
`assessment_policy`. It defines no new policy — it presents what those tables already
say so a UI can render "1.4.3 — Contrast (Minimum)" and count eligible files, and it
never scans, mutates, or persists anything.
"""
from __future__ import annotations

from collections.abc import Iterable

import assessment_policy as _policy

# Human-readable SC titles come from the server-side rule catalog, the single source of
# truth for these labels, so the code-set can never drift from the rest of the product.
_NAME_BY_CODE: dict[str, str] = {r["id"]: r["name"] for r in _policy.RULE_CATALOG}

# Last-resort fallback for the Core 17 only, used if a row ever went missing from
# RULE_CATALOG. These are the stable published WCAG titles.
_CORE17_NAMES: dict[str, str] = {
    "1.1.1": "Non-text Content",
    "1.3.1": "Info and Relationships",
    "1.3.2": "Meaningful Sequence",
    "1.3.3": "Sensory Characteristics",
    "1.4.1": "Use of Color",
    "1.4.3": "Contrast (Minimum)",
    "1.4.5": "Images of Text",
    "1.4.11": "Non-text Contrast",
    "2.1.1": "Keyboard",
    "2.1.2": "No Keyboard Trap",
    "2.4.2": "Page Titled",
    "2.4.3": "Focus Order",
    "2.4.4": "Link Purpose (In Context)",
    "2.4.6": "Headings and Labels",
    "3.1.1": "Language of Page",
    "3.1.2": "Language of Parts",
    "4.1.2": "Name, Role, Value",
}


def core17_codes() -> list[str]:
    """The Core-17 Success-Criterion ids, sorted (`assessment_policy.MOVA_TRACKED`)."""
    return sorted(_policy.MOVA_TRACKED)


def _name_for(code: str) -> str:
    return _NAME_BY_CODE.get(code) or _CORE17_NAMES.get(code) or code


def _formats_by_code() -> dict[str, frozenset[str]]:
    """Per-SC assessment-lane formats for the Core 17.

    Sourced from the `acp-core-17` scope preset — the materialized
    `SCOPE_UNIVERSE ∩ MOVA_TRACKED` (see `assessment_policy.SCOPE_PRESETS`). That preset
    IS "every format the engine can reach a verdict for" for the tracked set, and it
    already accounts for the registry-backed docx lanes that bare `RULE_FORMATS` cannot
    express — so the catalog and the scope grid cannot disagree about a criterion's lanes.

    Falls back to `RULE_FORMATS` (minus the html axis, which the scope grid excludes) for
    any Core-17 code the preset somehow omits.
    """
    preset = _policy.SCOPE_PRESETS.get("acp-core-17", {})
    out: dict[str, frozenset[str]] = {}
    for code in _policy.MOVA_TRACKED:
        fmts = preset.get(code)
        if fmts is None:
            fmts = frozenset(f for f in _policy.RULE_FORMATS.get(code, frozenset()) if f != "html")
        out[code] = frozenset(fmts)
    return out


def core17_catalog() -> list[dict]:
    """The Core-17 catalog a UI renders as the selectable code-set.

    `[{code, name, formats:[...]}, ...]`, sorted by code — e.g.
    `{"code": "1.4.3", "name": "Contrast (Minimum)", "formats": ["docx","pdf","pptx","xlsx"]}`.
    """
    fmts = _formats_by_code()
    return [
        {"code": code, "name": _name_for(code), "formats": sorted(fmts.get(code, frozenset()))}
        for code in core17_codes()
    ]


def parse_codes(raw: str | None) -> list[str]:
    """A comma-separated SC list → a validated, sorted Core-17 subset.

    Blank / None → the full Core 17 (the default selection). Unknown or non-Core-17
    tokens are dropped rather than raising — a read-only preview must never 500 on a
    typo — and a list that selects nothing valid falls back to the full Core 17.
    """
    if not raw or not raw.strip():
        return core17_codes()
    picked: list[str] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if tok in _policy.MOVA_TRACKED and tok not in picked:
            picked.append(tok)
    return sorted(picked) if picked else core17_codes()


def formats_for_codes(codes: Iterable[str]) -> frozenset[str]:
    """Union of assessment-lane formats across the selected Core-17 codes."""
    by_code = _formats_by_code()
    out: set[str] = set()
    for c in codes:
        out |= set(by_code.get(c, frozenset()))
    return frozenset(out)


def eligibility(inventory: dict | None, codes: Iterable[str] | None = None) -> dict:
    """Read-only eligibility preview for a selected code-set over a discovery inventory.

    `inventory` is the `estate_inventory.summarize()` dict persisted at
    `scan_runs.scope.inventory` by the latest discovery run. A file is ELIGIBLE when its
    estate format has a lane for at least one selected code; the count and the by-format
    breakdown are read straight off the inventory's `by_format`.

    `None`/empty inventory (no discovery run yet) → zeros with the full shape, never an
    error. This function reads only — it starts no scan and mutates nothing.
    """
    selected = list(codes) if codes is not None else core17_codes()
    by_code = _formats_by_code()
    eligible_formats = formats_for_codes(selected)

    inv = inventory or {}
    by_format_all: dict = inv.get("by_format") or {}
    discovered = int(inv.get("discovered") or 0)

    eligible_by_format = {
        fmt: int(by_format_all.get(fmt) or 0)
        for fmt in sorted(eligible_formats)
        if int(by_format_all.get(fmt) or 0) > 0
    }
    eligible = sum(eligible_by_format.values())

    # Reflect, per selected code, its lanes AND how many discovered files those lanes
    # reach — so a UI can show which selected codes actually have eligible files.
    codes_out = []
    for code in selected:
        code_fmts = sorted(by_code.get(code, frozenset()))
        code_eligible = sum(int(by_format_all.get(f) or 0) for f in code_fmts)
        codes_out.append({
            "code": code,
            "name": _name_for(code),
            "formats": code_fmts,
            "eligible": code_eligible,
        })

    return {
        "discovered": discovered,
        "eligible": eligible,
        "by_format": eligible_by_format,
        "formats": sorted(eligible_formats),
        "codes": codes_out,
    }
