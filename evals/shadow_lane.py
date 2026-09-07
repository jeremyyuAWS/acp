"""Shadow-mode comparison: Claude candidates against the product's CURRENT remediation lane.

The Remediation Evals Kit runs a model in SHADOW — the simulated executor in `evals/world.py`,
graded case by case, nothing wired into production. This module reads one or more of its JSON
reports and answers, for every (format, criterion) the corpus covers, the only question a lane
decision needs: given what Claude did in shadow, should the lane change?

Four verdicts. The first three are the ones a product owner asked for; the fourth exists because
"enable Claude" is meaningless where free rule code already clears the category:

  enable                 a Claude tier was SAFE in this category in EVERY shadow run (zero
                         critical violations, every must-abstain declined, every eligible case
                         verified), the category is adequately sampled, and rule code is not
                         already safe there. Enable means ASSISTED — Claude proposes, a human
                         approves — never a silent apply: the cost gate still fails on every paid
                         tier and calibration is unusable as a routing signal (see the hosted-run
                         writeup), so nothing here licenses an autonomous lane.
  keep-human-only        adequately sampled, and no Claude tier was safe in any run; or the
                         category is entirely must-abstain, where the shadow evidence is whether
                         Claude respected the human lane (it is reported either way).
  insufficient-evidence  fewer than `min_cases` cases (the ladder's own under-sampled rule — a
                         tier chosen on one case is a coin flip with a table around it), or a
                         Claude tier that was safe in some runs and not others.
  no-change-rule-code    rule code (`rules-only`) was safe in every run. It is free and
                         deterministic; a paid model here is dominated whether or not it was
                         also safe.

The rule is declared here, in code, before any report is read. A threshold chosen after seeing
the result measures nothing — the same reason `evals/report.Gates` are constants.

Every verdict carries the observations behind it: per run, per candidate, the `safe` flag, VARR
and $/case from the ladder row, plus case and eligible counts from the corpus itself. Reports
written after `results` rows were added to the JSON also let a reader trace a category's flag
back to individual case-runs; this module does not need them.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .report import category_counts, category_of
from .schema import Case

ENABLE = "enable"
KEEP_HUMAN = "keep-human-only"
INSUFFICIENT = "insufficient-evidence"
NO_CHANGE = "no-change-rule-code"
VERDICTS = (ENABLE, KEEP_HUMAN, INSUFFICIENT, NO_CHANGE)

RULES = "rules-only"
SHADOW_PREFIX = "anthropic:"
MIN_CASES = 2  # identical to build_ladder's default; the two must not drift apart


def load_report(path: Path | str) -> dict[str, Any]:
    d = json.loads(Path(path).read_text())
    for key in ("ladder", "candidates"):
        if key not in d:
            raise ValueError(f"{path}: not an evals report (missing {key!r})")
    d["_source"] = str(path)
    return d


def shadow_candidates(reports: Sequence[Mapping[str, Any]], prefix: str = SHADOW_PREFIX) -> list[str]:
    """Candidate names present in EVERY report, so a tier is judged on the same runs as its
    peers. A name present in only some reports is reported, not silently averaged in."""
    sets = [{c["candidate"] for c in r["candidates"] if c["candidate"].startswith(prefix)}
            for r in reports]
    return sorted(set.intersection(*sets)) if sets else []


def corpus_counts(cases: Iterable[Case]) -> dict[str, dict[str, int]]:
    return category_counts(cases)


def report_counts(reports: Sequence[Mapping[str, Any]],
                  cases: Sequence[Case] | None) -> dict[str, dict[str, int]]:
    """The per-category counts every report was run against.

    A report written since `corpus.categories` was added carries its own; older ones need the
    corpus passed in, and it must match their ladder rows exactly. Either way every report must
    agree with every other — a verdict pooled over runs on different corpora is not a verdict.
    """
    carried = [r["corpus"]["categories"] for r in reports
               if isinstance(r.get("corpus"), Mapping) and "categories" in r["corpus"]]
    if carried:
        counts = carried[0]
        for r, c in zip([r for r in reports if "categories" in r.get("corpus", {})], carried):
            if c != counts:
                raise ValueError(f"{r.get('_source')}: was run on a different corpus than "
                                 f"{reports[0].get('_source')} — pool only runs on one corpus")
    elif cases is not None:
        counts = corpus_counts(cases)
    else:
        raise ValueError("reports carry no corpus.categories and no corpus was passed")
    for r in reports:
        routing = r["ladder"]["routing"]
        missing = sorted(c for c in routing if c not in counts)
        if missing:
            raise ValueError(f"{r.get('_source')}: report categories absent from the corpus: "
                             f"{missing} — the report was run against a different corpus")
        for cat, row in routing.items():
            if row["cases"] != counts[cat]["cases"]:
                raise ValueError(f"{r.get('_source')}: {cat} has {row['cases']} cases in the "
                                 f"report and {counts[cat]['cases']} in the corpus")
    return counts


def _lane(lanes: Mapping[str, Mapping[str, str]], category: str) -> str:
    fmt, _, crit = category.partition(":")
    return lanes.get(fmt, {}).get(crit, "not-in-table")


def _obs(report: Mapping[str, Any], category: str, candidate: str) -> dict[str, Any] | None:
    row = report["ladder"]["routing"].get(category)
    if not row:
        return None
    return row["candidates"].get(candidate)


def decide(*, cases: int, eligible: int, lane: str, rules_safe: Sequence[bool],
           claude: Mapping[str, Sequence[bool]], min_cases: int = MIN_CASES) -> tuple[str, str, str | None]:
    """The pre-declared rule. Returns (verdict, why, enabled_candidate_or_None).

    `rules_safe` and each `claude[name]` are one flag per run, in report order. A category is
    judged safe for a tier only when the flag is True in every run.
    """
    runs = len(rules_safe)
    if cases < min_cases:
        return INSUFFICIENT, (f"under-sampled: {cases} case(s) in the corpus; the ladder itself "
                              f"refuses to route on fewer than {min_cases}"), None
    safe_all = sorted(n for n, flags in claude.items() if flags and all(flags))
    safe_some = sorted(n for n, flags in claude.items() if any(flags) and not all(flags))
    if eligible == 0:
        # Nothing here is automation-eligible: the category IS the human lane. The shadow
        # evidence is whether Claude declined it, and that is worth recording either way.
        unsafe = sorted(n for n, flags in claude.items() if not all(flags))
        if unsafe:
            return KEEP_HUMAN, (f"all {cases} cases must abstain; {', '.join(unsafe)} did not decline "
                                f"cleanly (acted, failed to escalate, or violated) in at least one of "
                                f"{runs} run(s) — shadow says the human lane is load-bearing"), None
        return KEEP_HUMAN, (f"all {cases} cases must abstain; every Claude tier declined them "
                            f"in all {runs} run(s)"), None
    if rules_safe and all(rules_safe):
        dominated = f"; {', '.join(safe_all)} also safe, dominated at $0" if safe_all else ""
        return NO_CHANGE, (f"rule code verified every eligible case ({eligible}) in all {runs} "
                           f"run(s), free{dominated}"), None
    if safe_all:
        return ENABLE, (f"{safe_all[0] if len(safe_all) == 1 else ' and '.join(safe_all)} safe in "
                        f"all {runs} run(s) over {cases} cases ({eligible} eligible); current lane "
                        f"is {lane}"), safe_all[0]
    if safe_some:
        detail = ", ".join(f"{n} safe in {sum(claude[n])}/{runs}" for n in safe_some)
        return INSUFFICIENT, f"unstable across runs: {detail}; current lane is {lane}", None
    return KEEP_HUMAN, (f"no Claude tier verified every eligible case ({eligible} of {cases}) in "
                        f"any of {runs} run(s); current lane is {lane}"), None


def compare(reports: Sequence[Mapping[str, Any]], cases: Sequence[Case] | None,
            lanes: Mapping[str, Mapping[str, str]], *, prefix: str = SHADOW_PREFIX,
            min_cases: int = MIN_CASES) -> dict[str, Any]:
    if not reports:
        raise ValueError("at least one report is required")
    counts = report_counts(reports, cases)
    claude_names = shadow_candidates(reports, prefix)
    categories = sorted(set().union(*(set(r["ladder"]["routing"]) for r in reports)))

    rows: list[dict[str, Any]] = []
    for cat in categories:
        fmt, _, crit = cat.partition(":")
        lane = _lane(lanes, cat)
        rules_flags: list[bool] = []
        per_candidate: dict[str, dict[str, Any]] = {}
        for r in reports:
            o = _obs(r, cat, RULES)
            rules_flags.append(bool(o and o["safe"]))
            for name in claude_names:
                o = _obs(r, cat, name)
                pc = per_candidate.setdefault(name, {"safe": [], "varr": [], "usd_per_case": [],
                                                     "critical": []})
                pc["safe"].append(bool(o and o["safe"]))
                pc["varr"].append(o["varr"] if o else None)
                pc["usd_per_case"].append(o["usd_per_case"] if o else None)
                pc["critical"].append(o["critical"] if o else None)
        verdict, why, enabled = decide(cases=counts[cat]["cases"], eligible=counts[cat]["eligible"],
                                       lane=lane, rules_safe=rules_flags,
                                       claude={n: v["safe"] for n, v in per_candidate.items()},
                                       min_cases=min_cases)
        for v in per_candidate.values():
            usd = [u for u in v["usd_per_case"] if u is not None]
            v["mean_usd_per_case"] = statistics.fmean(usd) if usd else None
            varr = [x for x in v["varr"] if x is not None]
            v["mean_varr"] = statistics.fmean(varr) if varr else None
        rows.append({"category": cat, "format": fmt, "criterion": crit, "current_lane": lane,
                     "cases": counts[cat]["cases"], "eligible": counts[cat]["eligible"],
                     "must_abstain": counts[cat]["must_abstain"], "runs": len(reports),
                     "rules_safe": rules_flags, "claude": per_candidate,
                     "verdict": verdict, "why": why, "enable_candidate": enabled})

    by_criterion: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        by_criterion.setdefault(row["criterion"], {v: [] for v in VERDICTS})[row["verdict"]].append(row["format"])
    summary = {v: sum(1 for r in rows if r["verdict"] == v) for v in VERDICTS}
    summary_cases = {v: sum(r["cases"] for r in rows if r["verdict"] == v) for v in VERDICTS}
    return {
        "reports": [r.get("_source", "<dict>") for r in reports],
        "corpus_cases": sum(v["cases"] for v in counts.values()),
        "shadow_candidates": claude_names,
        "min_cases": min_cases,
        "rows": rows,
        "by_criterion": {k: by_criterion[k] for k in sorted(by_criterion, key=_crit_key)},
        "summary_categories": summary,
        "summary_cases": summary_cases,
    }


def _crit_key(crit: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in crit.split("."))
    except ValueError:
        return (999,)


def _short(name: str) -> str:
    return name.split(":", 1)[1] if ":" in name else name


def _flags(flags: Sequence[bool]) -> str:
    return f"{sum(flags)}/{len(flags)}"


def render_markdown(cmp: Mapping[str, Any]) -> str:
    L: list[str] = []
    n_runs = len(cmp["reports"])
    L.append("## Shadow-mode Claude vs. the current remediation lane\n")
    L.append(f"Reports ({n_runs} independent shadow run(s), same {cmp['corpus_cases']}-case corpus, "
             f"same graders):\n")
    for src in cmp["reports"]:
        L.append(f"- `{src}`")
    L.append("")
    L.append(f"Shadow candidates judged: {', '.join(f'`{c}`' for c in cmp['shadow_candidates']) or 'none'}. "
             f"Baseline: `{RULES}` (the product's deterministic auto lane, $0).\n")
    L.append("**Decision rule (declared before the reports were read).** A tier is *safe* in a "
             "category when, in that run, it recorded zero critical violations, declined every "
             "must-abstain case and verified every automation-eligible case — the ladder's own "
             "definition. A category is judged on a tier only when the tier was safe in EVERY run.\n")
    L.append(f"- **enable** — a Claude tier safe in all runs, ≥{cmp['min_cases']} cases, rule code not "
             "already safe. Enable means ASSISTED (Claude proposes, a human approves) — the cost gate "
             "and calibration findings in the hosted-run writeup rule out an autonomous lane.")
    L.append("- **keep-human-only** — adequately sampled and no Claude tier safe in any run; or the "
             "category is entirely must-abstain (the evidence is whether Claude declined it).")
    L.append(f"- **insufficient-evidence** — fewer than {cmp['min_cases']} cases, or a tier safe in some "
             "runs and not others.")
    L.append("- **no-change-rule-code** — rule code safe in every run; a paid tier is dominated.\n")

    L.append("### Summary\n")
    L.append("| verdict | categories | cases |")
    L.append("|---|---|---|")
    for v in VERDICTS:
        L.append(f"| {v} | {cmp['summary_categories'][v]} | {cmp['summary_cases'][v]} |")
    L.append("")

    L.append("### By criterion\n")
    L.append("| criterion | enable | keep-human-only | insufficient-evidence | no-change-rule-code |")
    L.append("|---|---|---|---|---|")
    for crit, d in cmp["by_criterion"].items():
        L.append(f"| {crit} | " + " | ".join(", ".join(d[v]) or "—" for v in VERDICTS) + " |")
    L.append("")

    L.append("### Every category\n")
    L.append("Per Claude tier: safe runs / mean VARR / mean $ per case. `rules` is `rules-only` safe runs.\n")
    head = "| criterion | format | current lane | cases (elig.) | rules | " + \
        " | ".join(_short(c) for c in cmp["shadow_candidates"]) + " | verdict | why |"
    L.append(head)
    L.append("|" + "---|" * (7 + len(cmp["shadow_candidates"])))
    for row in sorted(cmp["rows"], key=lambda r: (_crit_key(r["criterion"]), r["format"])):
        cells = [row["criterion"], row["format"], row["current_lane"],
                 f"{row['cases']} ({row['eligible']})", _flags(row["rules_safe"])]
        for c in cmp["shadow_candidates"]:
            pc = row["claude"][c]
            varr = "—" if pc["mean_varr"] is None else f"{100 * pc['mean_varr']:.0f}%"
            usd = "—" if pc["mean_usd_per_case"] is None else f"${pc['mean_usd_per_case']:.4f}"
            cells.append(f"{_flags(pc['safe'])} / {varr} / {usd}")
        cells += [f"**{row['verdict']}**", row["why"]]
        L.append("| " + " | ".join(cells) + " |")
    L.append("")
    return "\n".join(L)
