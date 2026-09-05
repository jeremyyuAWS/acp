"""Per-file WCAG scope resolution (Discover/Assess Lifecycle PRD §4.4 / AC-09). Pure logic,
no DB — mirrors the `api/disposition.py` seam (validation + evaluation, persistence lives in
`api/store.py`).

A *scope rule* targets a set of files by **folder / owner / department / SharePoint Content
Type** and assigns a WCAG
code-set (a subset of Core-17). At assessment time a file's *effective* code-set is resolved
from the rules that match it, so e.g. Finance folders can be assessed against one code-set while
HR-owned content uses another.

Resolution — PRD §4.4, "combine the applicable WCAG codes unless an authorized user defines an
explicit higher-priority override":

  * the UNION of the codes of every enabled matching rule, UNLESS
  * one or more matching rules is an override, in which case the single highest-priority
    override REPLACES the union with its own codes. Ties are broken by rule_id so the result is
    deterministic (AC-09, "deterministic precedence for overlapping rules").
  * if no rule matches, the file keeps `default_codes` (the global Assess selection) — scope
    rules are refinements over the default, never a silent narrowing to the empty set.

A `file` is a dict with any subset of `path`, `parent_folder`, `owner`, `department`,
`content_type`. A `rule`
is a dict: {rule_id, selector, value, codes(list), priority(int), is_override(bool),
enabled(bool)}; `selector` ∈ SELECTORS.
"""
from __future__ import annotations

SELECTORS = ("folder", "owner", "department", "content_type")


def _norm(s) -> str:
    return (s or "").strip().lower()


def matches(file: dict, rule: dict) -> bool:
    """True iff `file` is targeted by `rule`.

    folder     — case-insensitive path PREFIX (matched against `path`, falling back to
                 `parent_folder`), so a rule value of "Finance" targets everything under it.
    owner       — case-insensitive equality against `owner`.
    department  — case-insensitive equality against `department`.
    content_type — case-insensitive equality against SharePoint's native Content Type.

    A blank rule value never matches — a rule that silently targeted every file would be a
    footgun, not a feature.
    """
    sel = rule.get("selector")
    val = _norm(rule.get("value"))
    if not val or sel not in SELECTORS:
        return False
    if sel == "folder":
        path = _norm(file.get("path"))
        pf = _norm(file.get("parent_folder"))
        return (bool(path) and path.startswith(val)) or (bool(pf) and (pf == val or pf.startswith(val)))
    if sel == "owner":
        return _norm(file.get("owner")) == val
    if sel == "department":
        return _norm(file.get("department")) == val
    if sel == "content_type":
        return _norm(file.get("content_type")) == val
    return False


def resolve(file: dict, rules: list[dict], default_codes) -> set:
    """Resolve `file`'s effective WCAG code-set from `rules`. See the module docstring for the
    union / override precedence. `default_codes` is returned (as a set) when no rule matches."""
    matching = [r for r in rules if r.get("enabled", True) and matches(file, r)]
    if not matching:
        return set(default_codes)
    overrides = [r for r in matching if r.get("is_override")]
    if overrides:
        # Highest priority wins; deterministic tie-break by rule_id so overlapping overrides
        # never resolve non-deterministically (AC-09).
        winner = max(overrides, key=lambda r: (r.get("priority", 0) or 0, str(r.get("rule_id", ""))))
        return set(winner.get("codes") or [])
    out: set = set()
    for r in matching:
        out.update(r.get("codes") or [])
    return out


def validate_scope_rule(rule: dict, allowed_codes) -> None:
    """Raise ValueError on a malformed rule — call before persisting. `allowed_codes` is the
    permitted WCAG set (Core-17); codes outside it are rejected so a rule can never scope a file
    to a criterion the product does not track."""
    if rule.get("selector") not in SELECTORS:
        raise ValueError(f"selector must be one of {list(SELECTORS)}, got {rule.get('selector')!r}")
    if not str(rule.get("value") or "").strip():
        raise ValueError("scope rule value must be non-empty")
    codes = rule.get("codes")
    if not isinstance(codes, (list, tuple)) or not codes:
        raise ValueError("scope rule must select at least one WCAG code")
    bad = [c for c in codes if c not in set(allowed_codes)]
    if bad:
        raise ValueError(f"codes not in the allowed Core-17 set: {sorted(bad)}")
