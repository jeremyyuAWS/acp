"""Versioned, content-addressed compliance rubric (Phase-4 seed).

Supersedes result_model.py. A rubric is a JSON config (config/rubric.default.json)
resolved at scan time and stamped on every result via a stable `rubric_hash` so runs
are reproducible (cf. ADR 102 prompt-hash identity).

Scoring keeps the Track-A safety rule — incomplete analysis is never a pass:
  ERROR     file unopenable           -> unscored, not certifiable
  UNCERTAIN >=1 rule threw & skipped   -> score is an UPPER BOUND, not certifiable
  ANALYSED  full run                   -> trustworthy; only this can be certified
Plus a per-WCAG-criterion breakdown and a per-run aggregate.
"""
from __future__ import annotations
import hashlib
import json
from enum import Enum
from pathlib import Path


class Status(str, Enum):
    ANALYSED = "analysed"
    UNCERTAIN = "uncertain"
    ERROR = "error"


class Rubric:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg.get("name", "rubric")
        self.version = cfg.get("version", "0")
        self.weights = cfg["severity_weights"]
        self.threshold = cfg["compliant_threshold"]
        self.disabled = set(cfg.get("disabled_rules", []))
        self.criteria = cfg.get("criteria", {})
        # stable content hash — same config (any key order) -> same id
        canon = json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode()
        self.hash = hashlib.sha256(canon).hexdigest()[:16]

    @classmethod
    def load(cls, path) -> "Rubric":
        return cls(json.loads(Path(path).read_text()))

    def _penalty(self, severity: str) -> int:
        return self.weights.get(severity, self.weights.get("_default", 5))

    def assess(self, succeeded: bool, issues: list, errors: list) -> dict:
        # rubric resolution: drop disabled rules' issues
        issues = [i for i in issues if i.get("ruleId") not in self.disabled]
        status = (Status.ERROR if not succeeded
                  else Status.UNCERTAIN if errors else Status.ANALYSED)
        score = None if status is Status.ERROR else max(
            0, 100 - sum(self._penalty(i["severity"]) for i in issues))

        fails: dict[str, int] = {}
        for i in issues:
            fails[i["wcag"]] = fails.get(i["wcag"], 0) + 1
        per_criterion = [
            {
                "criterion": key, "name": meta.get("name"), "level": meta.get("level"),
                "issues": fails.get(key, 0),
                "result": ("fail" if fails.get(key, 0)
                           else "uncertain" if status is Status.UNCERTAIN else "pass"),
            }
            for key, meta in self.criteria.items()
        ]
        return {
            "status": status.value,
            "score": score,
            "skipped_rules": len(errors),
            "compliant": status is Status.ANALYSED and score is not None and score >= self.threshold,
            "score_is_upper_bound": status is Status.UNCERTAIN,
            "per_criterion": per_criterion,
            "rubric_hash": self.hash,
        }

    def aggregate(self, assessed: dict) -> dict:
        scored = [a["score"] for a in assessed.values() if a["score"] is not None]
        crit_fail: dict[str, int] = {}
        for a in assessed.values():
            for c in a["per_criterion"]:
                if c["result"] == "fail":
                    crit_fail[c["criterion"]] = crit_fail.get(c["criterion"], 0) + 1
        return {
            "rubric": f"{self.name} v{self.version}",
            "rubric_hash": self.hash,
            "files": len(assessed),
            "certifiable": sum(a["compliant"] for a in assessed.values()),
            "uncertain": sum(a["status"] == "uncertain" for a in assessed.values()),
            "error": sum(a["status"] == "error" for a in assessed.values()),
            "avg_score": round(sum(scored) / len(scored)) if scored else None,
            "criterion_failures": dict(sorted(crit_fail.items(), key=lambda kv: -kv[1])),
        }


def render_score(a: dict) -> str:
    if a["status"] == "error":
        return "n/a (could not analyse)"
    if a["status"] == "uncertain":
        return f"<={a['score']} (UNCERTAIN: {a['skipped_rules']} skipped)"
    return str(a["score"])
