"""Rubric & rule-catalog endpoints."""
from __future__ import annotations
import json

from fastapi import APIRouter
from pydantic import BaseModel

import core

router = APIRouter()


@router.get("/rubric")
def rubric():
    rb = core.active_rubric()
    return {"name": rb.name, "version": rb.version, "hash": rb.hash,
            "target": rb.cfg.get("conformance_target"), "threshold": rb.threshold,
            "criteria": rb.criteria}


@router.get("/rules")
def rules():
    catalog = json.loads((core.ACP / "config/rule-catalog.json").read_text())
    disabled = set(core.active_rubric().disabled)
    findings = core.store.rule_findings()
    # Exclude the _meta key; enrich each rule with runtime state.
    return {
        fmt: [
            {
                **r,
                "enabled": r["id"] not in disabled,
                "findings": findings.get(r["id"], 0),
                # wcag_level already present in the enriched catalog; fall back for
                # older catalog rows that only have the legacy wcag key.
                "level": r.get("wcag_level") or ("AA" if r.get("wcag") == "SC_1_4_3" else "A"),
            }
            for r in items
        ]
        for fmt, items in catalog.items()
        if fmt != "_meta"
    }


class RubricUpdate(BaseModel):
    disabled_rules: list[str] | None = None
    compliant_threshold: int | None = None


@router.put("/rubric")
def update_rubric(body: RubricUpdate):
    base = core.ACP / "config" / ("rubric.active.json" if (core.ACP / "config/rubric.active.json").exists()
                                  else "rubric.default.json")
    cfg = json.loads(base.read_text())
    if body.disabled_rules is not None:
        cfg["disabled_rules"] = sorted(set(body.disabled_rules))
    if body.compliant_threshold is not None:
        cfg["compliant_threshold"] = int(body.compliant_threshold)
    (core.ACP / "config/rubric.active.json").write_text(json.dumps(cfg, indent=2))
    rb = core.active_rubric()
    return {"hash": rb.hash, "disabled_rules": sorted(rb.disabled), "threshold": rb.threshold}
