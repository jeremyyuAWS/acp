"""What ACP can assess, and how a criterion's findings become a verdict.

Split out of store.py (ADR-less; see the commit that moved it). That module was doing three
unrelated jobs in 4,102 lines — persistence, the capability tables, and the outcome gate — so
someone asking "how is PASS decided?" had to know the answer lived inside the database layer.
Storage and policy are different concerns with different reasons to change, and only one of them
is about SQL.

Nothing here was rewritten. This is a move: the tables, the level/target arithmetic, the scope
gate and `_rule_outcome` are byte-for-byte what they were, and `store` re-exports every name so
`from store import RULE_FORMATS` keeps working exactly as before. That matters more than tidiness
here — this code decides whether a document passes, and a refactor that also changed behaviour
would be indistinguishable from one that broke it.

THE GATE STAYS SINGULAR. `_rule_outcome` is the one place a verdict is decided, and moving it did
not make it modular — deliberately. Scattering pass/fail into per-rule modules is how a rule ends
up certifying something it cannot judge, which is what PRs #26, #29 and #68 each fixed after the
fact, and what the `guard(assess)` commit ("route every PASS through one gate, so the lane cannot
be bypassed") exists to prevent. Modular where variety lives — detection, remediation, a rule's
own capability declaration. Single-path where correctness lives.
"""
from __future__ import annotations

# The only import the moved block needs; everything else it uses is a builtin or defined
# here. store.py still imports Path for its own use, so nothing was taken from it.
from pathlib import Path

# Rule catalog — mirrors frontend/src/rules/index.js.
# Used to compute per-file pass/fail/skip traces when saving scan results.
# fix_mode: 'auto' = deterministic, 'ai-assisted' = AI draft + human approve,
#           'human-only' = must be verified by a person.
# plain: a non-technical phrase for the rule, used in Langfuse span names and the
# Grafana "most common problems" panel (persisted to scan_rule_traces.plain_name).
# This is the single source of truth for the plain-English rule labels.
RULE_CATALOG: list[dict] = [
    {"id": "1.1.1",  "name": "Non-text Content",           "level": "A",   "fix_mode": "ai-assisted", "plain": "Images missing a text description"},
    {"id": "1.2.1",  "name": "Audio-only & Video-only",     "level": "A",   "fix_mode": "human-only",   "plain": "Audio/video with no transcript"},
    {"id": "1.2.2",  "name": "Captions (Prerecorded)",      "level": "A",   "fix_mode": "human-only",   "plain": "Video missing captions"},
    {"id": "1.2.3",  "name": "Audio Description or Alt",     "level": "A",   "fix_mode": "human-only",   "plain": "Video missing audio description or transcript"},
    {"id": "1.3.1",  "name": "Info and Relationships",      "level": "A",   "fix_mode": "auto",         "plain": "Structure not marked up (headings, lists, tables)"},
    {"id": "1.3.2",  "name": "Meaningful Sequence",         "level": "A",   "fix_mode": "auto",         "plain": "Reading order does not match the visual order"},
    {"id": "1.3.3",  "name": "Sensory Characteristics",      "level": "A",   "fix_mode": "human-only",   "plain": "Instructions rely on shape or position alone"},
    {"id": "1.3.4",  "name": "Orientation",                "level": "AA",  "fix_mode": "auto",         "plain": "Content locked to one screen orientation"},
    {"id": "1.3.5",  "name": "Identify Input Purpose",     "level": "AA",  "fix_mode": "auto",         "plain": "Form fields don't declare their purpose"},
    {"id": "1.4.1",  "name": "Use of Color",                "level": "A",   "fix_mode": "auto",         "plain": "Information shown by color alone"},
    {"id": "1.4.2",  "name": "Audio Control",              "level": "A",   "fix_mode": "auto",         "plain": "Autoplaying media that can't be stopped"},
    {"id": "1.4.3",  "name": "Contrast (Minimum)",          "level": "AA",  "fix_mode": "auto",         "plain": "Text with low color contrast"},
    {"id": "1.4.4",  "name": "Resize Text",                 "level": "AA",  "fix_mode": "auto",         "plain": "Text that can't be enlarged"},
    {"id": "1.4.5",  "name": "Images of Text",             "level": "AA",  "fix_mode": "ai-assisted", "plain": "Text baked into an image"},
    {"id": "1.4.6",  "name": "Contrast (Enhanced)",        "level": "AAA", "fix_mode": "auto",         "plain": "Text below the enhanced contrast ratio"},
    {"id": "1.4.8",  "name": "Visual Presentation",         "level": "AAA", "fix_mode": "human-only",   "plain": "Body text set justified (both margins)"},
    {"id": "1.4.9",  "name": "Images of Text (No Exception)", "level": "AAA", "fix_mode": "ai-assisted", "plain": "Any text baked into an image (no exceptions)"},
    {"id": "1.4.10", "name": "Reflow",                      "level": "AA",  "fix_mode": "auto",         "plain": "Content that doesn't reflow on small screens"},
    {"id": "1.4.11", "name": "Non-text Contrast",           "level": "AA",  "fix_mode": "ai-assisted", "plain": "Buttons or icons with low contrast"},
    {"id": "1.4.12", "name": "Text Spacing",                "level": "AA",  "fix_mode": "auto",         "plain": "Text spacing can't be adjusted"},
    {"id": "2.1.1",  "name": "Keyboard",                    "level": "A",   "fix_mode": "auto",         "plain": "Can't be used with a keyboard"},
    {"id": "2.1.2",  "name": "No Keyboard Trap",            "level": "A",   "fix_mode": "human-only",   "plain": "Embedded controls may trap keyboard focus"},
    {"id": "2.4.1",  "name": "Bypass Blocks",              "level": "A",   "fix_mode": "auto",         "plain": "No way to skip repeated navigation"},
    {"id": "2.4.2",  "name": "Page Titled",                 "level": "A",   "fix_mode": "auto",         "plain": "Missing a page or document title"},
    {"id": "2.4.3",  "name": "Focus Order",                 "level": "A",   "fix_mode": "auto",         "plain": "Illogical keyboard navigation order"},
    {"id": "2.4.4",  "name": "Link Purpose (In Context)",   "level": "A",   "fix_mode": "ai-assisted", "plain": "Unclear link text (e.g. 'click here')"},
    {"id": "2.4.6",  "name": "Headings and Labels",         "level": "AA",  "fix_mode": "auto",         "plain": "Unclear headings or labels"},
    {"id": "2.4.7",  "name": "Focus Visible",               "level": "AA",  "fix_mode": "auto",         "plain": "No visible keyboard focus indicator"},
    {"id": "2.4.9",  "name": "Link Purpose (Link Only)",  "level": "AAA", "fix_mode": "ai-assisted", "plain": "Same link text used for different destinations"},
    {"id": "2.4.10", "name": "Section Headings",           "level": "AAA", "fix_mode": "human-only",   "plain": "Long document has no section headings"},
    {"id": "2.5.3",  "name": "Label in Name",              "level": "A",   "fix_mode": "auto",         "plain": "Control names don't match their visible labels"},
    {"id": "2.5.8",  "name": "Target Size (Minimum)",       "level": "AA",  "fix_mode": "human-only",   "plain": "Touch targets smaller than 24px"},
    {"id": "3.1.1",  "name": "Language of Page",            "level": "A",   "fix_mode": "auto",         "plain": "Document language not set"},
    {"id": "3.1.2",  "name": "Language of Parts",           "level": "AA",  "fix_mode": "ai-assisted", "plain": "A passage's language not marked"},
    {"id": "3.1.4",  "name": "Abbreviations",               "level": "AAA", "fix_mode": "auto",         "plain": "Unexplained abbreviations"},
    {"id": "3.1.5",  "name": "Reading Level",               "level": "AAA", "fix_mode": "human-only",   "plain": "Text reading level well above lower-secondary"},
    {"id": "3.3.2",  "name": "Labels or Instructions",     "level": "A",   "fix_mode": "ai-assisted", "plain": "Required fields with no label or instructions"},
    {"id": "4.1.2",  "name": "Name, Role, Value",           "level": "A",   "fix_mode": "ai-assisted", "plain": "Controls missing names/roles for assistive tech"},
]

# Which document formats each RULE_CATALOG rule actually has a validator for.
# Without this, a rule that only runs for HTML (say) silently reads PASS on a
# PDF/DOCX/PPTX/XLSX file in scan_rule_traces — the check was never evaluated,
# but a zero finding-count looks identical to a real pass. tests/test_rule_formats.py
# derives this same table from source (api/scanner.py + ocr.py + textchecks.py +
# config/rule-catalog.json) and asserts it matches — kept in sync by hand, same
# posture as RULE_CATALOG vs frontend/src/rules/index.js's PLAIN_NAMES, but with
# an automated drift check this time.
_ALL_FORMATS = frozenset({"html", "docx", "pptx", "xlsx", "pdf"})
_OFFICE_PDF = frozenset({"docx", "pptx", "xlsx", "pdf"})
RULE_FORMATS: dict[str, frozenset[str]] = {
    "1.1.1": _ALL_FORMATS, "1.2.1": frozenset({"html"}), "1.2.2": frozenset({"html"}),
    "1.2.3": frozenset({"html"}), "1.3.1": _ALL_FORMATS, "1.3.2": _ALL_FORMATS, "1.3.3": _ALL_FORMATS,
    "1.3.4": frozenset({"html"}), "1.3.5": frozenset({"html"}), "1.4.1": frozenset({"html"}),
    "1.4.2": frozenset({"html", "pptx"}), "1.4.3": _ALL_FORMATS,
    "1.4.4": frozenset({"html"}), "1.4.5": _ALL_FORMATS, "1.4.6": frozenset({"html", "pdf", "pptx", "xlsx"}),
    "1.4.8": frozenset({"docx"}),
    "1.4.9": _OFFICE_PDF, "1.4.10": frozenset({"html"}), "1.4.11": frozenset({"html"}),
    "1.4.12": frozenset({"html"}), "2.1.1": frozenset({"pptx"}),
    # 2.1.2 No Keyboard Trap has NO pass/fail validator on any format — it is review-lane for
    # office (REVIEW_FORMATS, control-gated), needs-AT for html, and out of scope for pdf. An empty
    # set makes _rule_outcome fall through to REVIEW (office w/ controls) or NOT_EVALUATED (else),
    # never a fabricated PASS.
    "2.1.2": frozenset(),
    "2.4.1": frozenset({"html", "pdf"}),
    "2.4.2": _ALL_FORMATS, "2.4.3": frozenset({"html"}), "2.4.4": _ALL_FORMATS,
    "2.4.6": _ALL_FORMATS, "2.4.7": frozenset({"html"}), "2.4.9": frozenset({"docx", "html", "pptx"}),
    "2.4.10": frozenset({"docx"}),
    "2.5.3": frozenset({"html"}), "2.5.8": frozenset({"html"}), "3.1.1": _ALL_FORMATS,
    "3.1.2": _ALL_FORMATS, "3.1.4": frozenset({"html"}), "3.1.5": _ALL_FORMATS, "3.3.2": frozenset({"docx", "html"}),
    "4.1.2": frozenset({"html"}),
}


def _file_format(filename: str) -> str | None:
    """Canonical format name for a scanned filename, or None if unrecognized."""
    ext = Path(filename).suffix.lower()
    if ext in (".html", ".htm"):
        return "html"
    if ext in (".docx", ".pptx", ".xlsx"):
        return ext.lstrip(".")
    if ext == ".pdf":
        return "pdf"
    return None


# The outcome for a criterion this platform has no validator for, on this file's format.
#
# It used to be "NOT_APPLICABLE", which is a claim we cannot support. All the code knows is
# that no validator ran. Whether the criterion *applies* is a WCAG judgement no line of this
# module makes: 2.4.3 Focus Order and 4.1.2 Name/Role/Value genuinely do apply to a tagged
# PDF (PDF/UA specifies both), and we simply don't check them there. Telling an auditor
# "not applicable" asserts the criterion is out of scope; the truth is only that we didn't
# look. The weaker statement is the true one, so it is the only one we make.
#
# Anything genuinely out of scope must be curated by an accessibility specialist and stated
# explicitly — never inferred from the absence of an implementation.
NOT_EVALUATED = "NOT_EVALUATED"
_LEGACY_NOT_EVALUATED = "NOT_APPLICABLE"   # rows written before this rename; see _SCHEMA
REVIEW = "REVIEW"   # 🟡 advisory Review-Recommended outcome (ADR 0023) — assessed-for-review, never certified

# The outcomes that mean a queued review item has stopped being work, so the inbox retracts it
# (_superseded_items). Both are "nothing for a human to do here": PASS is certified conformant,
# NOT_EVALUATED is nobody asked. FAIL and REVIEW are absent on purpose — REVIEW especially, since
# it is the resting state of every criterion whose detector cannot certify a pass.
_SUPERSEDING_OUTCOMES = frozenset({"PASS", NOT_EVALUATED, _LEGACY_NOT_EVALUATED})

# ── Review-lane detectors (ADR 0023, Option A) ─────────────────────────────────
# The criteria + formats where ACP runs a REVIEW detector (surfaces evidence of a likely
# issue for a human to adjudicate) rather than a pass/fail validator. This is a SEPARATE map
# from RULE_FORMATS on purpose: a review-lane (criterion, format) resolves to REVIEW when its
# detector fires and to NOT_EVALUATED (genuine N/A) when it does not — it NEVER resolves to
# PASS, because ACP did not verify conformance (ADR 0016). Currently backed by the shipped
# office interactive-control detector (office_structure.office_control_review_checks).
REVIEW_FORMATS: dict[str, frozenset[str]] = {
    "2.1.2": frozenset({"docx", "pptx", "xlsx"}),   # No Keyboard Trap — controls present
    "4.1.2": frozenset({"docx", "pptx", "xlsx"}),   # Name/Role/Value — controls present
    "1.4.1": frozenset({"docx", "xlsx", "pdf"}),    # Use of Color — colour-only status/links (pdf: colour-only link, ADR 0025)
    "2.4.3": frozenset({"pptx"}),                   # Focus Order — title not first in reading order
    "1.4.11": frozenset({"pptx", "docx", "pdf"}),   # Non-text Contrast — faint shape outline (docx/pdf shapes too)
    # ADR 0024 Tier A — render-gated structural proxies (no rendering). 1.4.3 is NOT here: its
    # hybrid text-over-non-solid REVIEW rides the existing 1.4.3 pass/fail lane (a solid-fill FAIL
    # still wins), so it must not be diverted to the review-only lane.
    "1.4.4": frozenset({"pptx"}),                   # Resize Text — fixed-size text box, no auto-fit
    "1.4.10": frozenset({"docx", "pptx"}),          # Reflow — table too wide to reflow
    "1.4.12": frozenset({"docx", "pptx", "pdf"}),   # Text Spacing — exact line spacing (docx/pptx); tight line pitch (pdf, ADR 0025)
}

# Criteria ACP CANNOT CERTIFY A PASS for, even though they have a pass/fail detector — every
# assessment lane except 🟢 auto (ADR 0023). Derived from remediation_capability.assessment_table().
# Used by _rule_outcome so such a criterion with NO finding resolves to REVIEW ("assessed for
# review, not certified"), never a green PASS — keeping the estate rollup honest and consistent
# with the per-file drawer + the scorecard (audit #174).
#
# The test is `lane != auto`, NOT `lane == review`, and that distinction is the whole point. Only
# 🟢 auto means "ACP certifies a PASS from a deterministic fact"; every other lane means it cannot.
# Selecting the certifying lane and inverting it is safe by construction — a lane added later is
# non-certifying until someone proves otherwise, which is the direction that fails safe.
#
# Enumerating the NON-certifying lanes instead is what shipped, and it silently omitted 🔴 human.
# That is not a hypothetical: pptx 2.1.1 Keyboard is the single 🔴 cell in the table, and it has NO
# 2.1.1 detector on any pptx code path (office_structure.checks_for dispatches ten pptx checks and
# not one emits 2.1.1). It sits in RULE_FORMATS regardless, so bare membership was read as "the
# validator ran", and a clean deck resolved to a certified green PASS on a criterion the lane table
# in the same breath said only a person could judge — keyboard operability being a property of the
# runtime that presents a deck, never of the file. Third instance of this shape after docx 2.4.6
# (#29-era) and html 2.4.6 (#26); those two were 🟡 cells fixed one at a time. Widening the
# selector retires the class rather than the instance, and the guard test in
# tests/test_review_outcome.py asserts no non-🟢 lane can return PASS on any format.
try:
    import remediation_capability as _cap_mod
    _no_certify: dict[str, set[str]] = {}
    for _fmt, _scs in _cap_mod.assessment_table().items():
        for _sc, _lane in _scs.items():
            if _lane != _cap_mod.A_AUTO:
                _no_certify.setdefault(_sc, set()).add(_fmt)
    NO_CERTIFY_ASSESS_FORMATS: dict[str, frozenset[str]] = {k: frozenset(v) for k, v in _no_certify.items()}
except Exception:
    NO_CERTIFY_ASSESS_FORMATS = {}


# ── Conformance target ────────────────────────────────────────────────────────
# WCAG levels nest: A ⊆ AA ⊆ AAA. Assessing "at level AA" means assessing every criterion at
# AA OR BELOW — so a target of AA covers A and AA, and a target of A covers only A.
#
# Only A and AA are selectable. AAA is a real level in the catalog (1.4.6, 1.4.8, 1.4.9, 2.4.9,
# 2.4.10, 3.1.4, 3.1.5 all carry it) and several detectors emit AAA findings as a by-product of
# their AA work — the contrast checks compute both thresholds in one pass. Those findings were
# being recorded and scored against files whose target was AA, which reports a document as
# failing a bar nobody asked it to meet.
LEVEL_RANK: dict[str, int] = {"A": 1, "AA": 2, "AAA": 3}
TARGET_LEVELS: tuple[str, ...] = ("A", "AA")     # what a user may choose
DEFAULT_TARGET = "AA"

_SC_LEVEL: dict[str, str] = {r["id"]: (r.get("level") or "A") for r in RULE_CATALOG}


def parse_target(value: str | None) -> str:
    """'WCAG 2.1 AA' / 'aa' / None -> 'AA'. The rubric stores a display string, not a bare level.

    Anything unrecognised falls back to the default rather than raising: a malformed target must
    not take a scan down, and AA is both the common case and the safer one (it assesses more
    than A, so nothing is silently skipped by a typo)."""
    token = str(value or "").strip().upper().split()[-1] if value else ""
    return token if token in TARGET_LEVELS else DEFAULT_TARGET


_CONFIG_TARGET: str | None = None


def config_target() -> str:
    """The conformance target from the active rubric (config/rubric.default.json).

    Cached: this is read on every persisted file and the value cannot change without a restart,
    since the rubric is content-addressed and a different rubric is a different scan.
    """
    global _CONFIG_TARGET
    if _CONFIG_TARGET is None:
        try:
            import json as _json
            cfg = _json.loads((Path(__file__).resolve().parent.parent / "config"
                               / "rubric.default.json").read_text())
            _CONFIG_TARGET = parse_target(cfg.get("conformance_target"))
        except Exception:
            _CONFIG_TARGET = DEFAULT_TARGET
    return _CONFIG_TARGET


def in_target(rule_id: str, target: str | None = None) -> bool:
    """Is this criterion at or below the conformance target the scan was run for?"""
    tgt = LEVEL_RANK.get(parse_target(target), LEVEL_RANK[DEFAULT_TARGET])
    return LEVEL_RANK.get(_SC_LEVEL.get(rule_id, "A"), 1) <= tgt


def filter_issues_to_target(issues: list[dict], target: str | None = None) -> list[dict]:
    """Drop findings for criteria above the target level.

    Applied where counts are computed rather than where issues are stored: the raw findings stay
    on the record, so re-reporting the same scan at a different target needs no re-scan. What
    changes is what gets ASSESSED and scored — which is what the target actually means.
    """
    out = []
    for i in issues:
        sc = _extract_sc(i.get("wcag", ""))
        if not sc or in_target(sc, target):
            out.append(i)
    return out


# ── Capability registry bridge ────────────────────────────────────────────────
# Imported lazily and defensively. store.py is imported by a lot of tooling that has no
# business pulling in pikepdf and the format parsers, and a registry that fails to load must
# degrade to the legacy tables rather than take the scan down with it — an unmigrated pair
# behaves exactly as it did before the registry existed, which is what makes the migration
# safe to do one pair at a time.
_CAN_CERTIFY_PASS: frozenset = frozenset()
_NEEDS_REVIEW_ON_CLEAN: frozenset = frozenset()
_registry_mod = None
_registry_failed = False


def _registry_for(rule_id: str, fmt: str | None):
    """The registration for a pair, or None when it hasn't been migrated (or can't load)."""
    global _registry_mod, _registry_failed, _CAN_CERTIFY_PASS, _NEEDS_REVIEW_ON_CLEAN
    if fmt is None or _registry_failed:
        return None
    if _registry_mod is None:
        try:
            import assessment as _a
            import rule_registry as _r
            _r.load()
            _CAN_CERTIFY_PASS = _a.CAN_CERTIFY_PASS
            _NEEDS_REVIEW_ON_CLEAN = _a.NEEDS_REVIEW_ON_CLEAN
            _registry_mod = _r
        except Exception:
            _registry_failed = True
            return None
    return _registry_mod.get(rule_id, fmt)


def _certify(rule_id: str, fmt: str | None) -> str:
    """The strongest outcome a CLEAN scan may claim for this pair: PASS, or REVIEW if the
    assessment lane says ACP cannot certify it.

    THE single gate for the token "PASS". Every route through _rule_outcome that would certify
    must return through here, so the lane can never be bypassed by adding one more route.

    That is not a style preference — it is the defect this function exists to prevent, twice
    over. The lane check was originally written inline at the one place a clean pass/fail scan
    could certify. The registry branch (ADR 0024 coverage axis) was then added ABOVE it with its
    own `return "PASS"`, and a FULL-coverage registration certified without ever consulting the
    lane. Coverage and lane answer different questions: FULL says "our technique reaches the
    whole criterion", the lane says "a pass here is a judgement ACP cannot make at all". When
    they disagree the lane wins, because no amount of detector reach makes a subjective
    criterion objectively certifiable.

    It did not fire in production only because no FULL-coverage registration happened to sit on
    a 🟡/🔴 pair — html 3.1.1, the only FULL cell, is 🟢 auto. The two PDF registrations are
    PARTIAL and HEURISTIC, so PDF was never exposed. A single future migration to FULL would
    have resurrected pptx 2.1.1's fabricated green on a different format (verified by doing
    exactly that to pdf 1.1.1, whose lane is 🟡 review: it returned PASS).
    """
    if fmt in NO_CERTIFY_ASSESS_FORMATS.get(rule_id, frozenset()):
        return REVIEW
    return "PASS"


# ── Operator-selected scan scope ──────────────────────────────────────────────────────
# RULE_FORMATS already says which formats a criterion CAN be evaluated on. This is the
# narrower question an operator asks: which of those they want evaluated for THIS engagement.
#
# The two are different in kind and must not be conflated. RULE_FORMATS is a fact about the
# code — 2.4.3 cannot be judged on docx because no detector exists. Scope is a choice — a
# customer's checklist covers 14 criteria and not the other six. Out-of-scope reads
# NOT_EVALUATED, exactly like an above-target criterion: we did not evaluate it, because
# nobody asked us to.
#
# Stored as a setting rather than code so it survives a redeploy and is auditable. None (the
# default) means no restriction — everything RULE_FORMATS allows.
#
# WHY THIS IS NOT A FILE-TYPE FILTER. The obvious implementation — "don't scan .pptx" — is
# coarser and dishonest in a way this is not: dropping a whole format removes its findings AND
# its passes from the denominator, so excluding a format tends to flatter the score. Scoping by
# (criterion, format) leaves every file scanned and every in-scope result counted; only the
# pairs nobody asked about go quiet.
SCOPE_PRESETS: dict[str, dict[str, frozenset[str]]] = {
    # Deva's FINAL tab, IN-SCOPE grid — 14 criteria, per-format. Mirrors V5_APPLICABLE in the
    # WCAG matrix, which was built from the same sheet; the two must not drift.
    "deva-final": {
        "1.1.1": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "1.3.1": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "1.3.2": frozenset({"pptx", "pdf"}),
        "1.4.1": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "1.4.3": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "1.4.5": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "2.1.1": frozenset({"pptx", "pdf"}),
        "2.4.2": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "2.4.3": frozenset({"pptx", "pdf"}),
        "2.4.4": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "2.4.6": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "3.1.1": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "3.1.2": frozenset({"docx", "xlsx", "pptx", "pdf"}),
        "4.1.2": frozenset({"pdf"}),
    },
}

SCOPE_SETTING = "scan_scope"          # preset name, or "" / absent for no restriction
_scope_override: str | None = None    # tests and per-call use; None = read the setting


def active_scope(store=None) -> dict[str, frozenset[str]] | None:
    """The (criterion -> formats) map currently in force, or None for no restriction."""
    name = _scope_override
    if name is None and store is not None:
        try:
            name = store.get_setting(SCOPE_SETTING, "") or ""
        except Exception:
            name = ""
    return SCOPE_PRESETS.get(name or "")


def in_scope(rule_id: str, fmt: str | None, scope: dict | None = None) -> bool:
    """False only when a scope is set AND it excludes this (criterion, format).

    An unknown format is never excluded: the gate's job is to honour a deliberate choice, not
    to invent one from a filename it could not parse.
    """
    if scope is None:
        scope = active_scope()
    if not scope:
        return True
    if fmt is None:
        return True
    fmts = scope.get(rule_id)
    return bool(fmts) and fmt in fmts


def _rule_outcome(rule_id: str, fmt: str | None, fail_count: int, review_count: int = 0,
                  target: str | None = None) -> str:
    """The per-(criterion, format) outcome from its finding counts.

    `fail_count` = blocking findings, `review_count` = advisory (severity REVIEW) findings.
    Review-lane pairs (REVIEW_FORMATS): a signal → REVIEW, none → NOT_EVALUATED — NEVER PASS,
    because a review detector doesn't certify conformance (ADR 0016). Pass/fail-lane pairs: FAIL
    if a blocking finding fired, else PASS if the validator ran, else NOT_EVALUATED. An advisory
    review finding on a pass/fail-lane criterion (rare) surfaces as REVIEW only when nothing
    blocking fired. A definite FAIL always outranks an advisory REVIEW.

    `target` is the conformance level the scan was run for (A or AA). A criterion ABOVE it is
    not assessed at all — see the gate below."""
    # Conformance target gate, before everything else including the blocking-finding hoist.
    #
    # A criterion above the target was never in scope, so there is nothing to report about it —
    # not a pass, not a fail, and not a review. It reads NOT_EVALUATED, which is literally what
    # happened: we did not evaluate it, because the scan was run for a lower level.
    #
    # This deliberately outranks the "a recorded finding is a FACT" hoist below, and that is the
    # one place in this function where a finding does not surface. The justification is that the
    # finding should never have been collected: several detectors compute AA and AAA thresholds
    # in a single pass (the contrast checks do), so an AAA finding can exist on an AA scan as a
    # by-product. Reporting it would fail a document against a bar nobody asked it to meet.
    # `filter_issues_to_target` drops those upstream; this is the backstop for callers that
    # pass raw counts.
    if not in_target(rule_id, target):
        return NOT_EVALUATED
    # Operator scope gate, on the same footing as the target gate above and for the same
    # reason: a pair nobody put in scope was never evaluated, so it reports neither pass nor
    # fail. Placed after the target gate because level is the coarser filter.
    if not in_scope(rule_id, fmt):
        return NOT_EVALUATED
    if fmt is not None and fmt in REVIEW_FORMATS.get(rule_id, frozenset()):
        if fail_count > 0:
            return "FAIL"
        return REVIEW if review_count > 0 else NOT_EVALUATED
    # A recorded blocking finding is a FACT: it must surface as FAIL no matter what the format
    # bookkeeping says. Before this hoist, a fail on a (rule, format) pair missing from
    # RULE_FORMATS was silently reclassified NOT_EVALUATED — the exact detector/catalog-drift
    # hazard the no-silent-gaps contract test exists to catch (a finding visible in the drawer
    # while its manifest row claimed "not checked").
    if fail_count > 0:
        return "FAIL"
    # ── Registry-backed pairs (api/rule_registry.py) ──────────────────────────────────
    # For a (criterion, format) that has been migrated to the capability registry, COVERAGE
    # decides what a clean scan is worth — the thing RULE_FORMATS cannot express.
    #
    # 4.1.2 and 2.4.3 on PDF are why this exists. Both run a real detector on every PDF, but
    # only over AcroForm fields, and neither pair appeared in RULE_FORMATS or REVIEW_FORMATS.
    # So a clean scan fell through to NOT_EVALUATED — "we did not look" — for work that had in
    # fact been done. Partial coverage can't certify a pass either, so the honest answer is
    # REVIEW: we checked what our technique reaches, a human confirms the rest.
    reg = _registry_for(rule_id, fmt)
    if reg is not None:
        if review_count > 0:
            return REVIEW
        if reg.coverage in _CAN_CERTIFY_PASS:
            # Through the gate, never a bare `return "PASS"`: FULL coverage is a claim about the
            # DETECTOR's reach, and it does not override a lane that says ACP cannot certify at
            # all. See _certify.
            return _certify(rule_id, fmt)
        if reg.coverage in _NEEDS_REVIEW_ON_CLEAN:
            return REVIEW
        return NOT_EVALUATED          # DECLARED / UNSUPPORTED — applicable, nothing ran
    if fmt is None or fmt not in RULE_FORMATS.get(rule_id, _ALL_FORMATS):
        return NOT_EVALUATED
    if review_count > 0:
        return REVIEW
    # Validator ran, no finding. A 🟢 auto-assess criterion → a certified PASS. Any other lane
    # (🟡 review or 🔴 human — ACP can't certify it, see NO_CERTIFY_ASSESS_FORMATS) is NOT a pass:
    # it stays REVIEW, never a fabricated green (ADR 0016 / audit #174).
    return _certify(rule_id, fmt)


def _split_sc_counts(issues: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Per-SC finding counts split into (blocking, advisory-review). A finding is advisory when
    its severity is REVIEW (ADR 0023); everything else is blocking. Both keyed by 'X.Y.Z' SC."""
    fail_counts: dict[str, int] = {}
    review_counts: dict[str, int] = {}
    for i in issues:
        sc = _extract_sc(i.get("wcag", ""))
        if not sc:
            continue
        bucket = review_counts if str(i.get("severity", "")).upper() == REVIEW else fail_counts
        bucket[sc] = bucket.get(sc, 0) + 1
    return fail_counts, review_counts


def _pages_csv(pages: list[int]) -> str | None:
    """Compact, capped rendering of the distinct pages a criterion fails on."""
    return ",".join(str(p) for p in pages[:12]) if pages else None


def _extract_sc(wcag: str) -> str:
    """Extract the 'X.Y.Z' SC number from any wcag field format.
    Handles: '1.1.1', '1.1.1 Non-text Content', 'SC_1_1_1', 'wcag111'."""
    import re as _re
    m = _re.search(r'(\d+)[._](\d+)[._](\d+)', wcag or '')
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else ""


