"""Dedicated Assess and Remediate services must never consume each other's capacity."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


def test_assess_and_remediate_roles_are_disjoint(monkeypatch, isolated_store):
    import core
    import handlers  # noqa: F401 — register handlers

    assess = isolated_store.enqueue_job("scan_assess", {})
    remediation = isolated_store.enqueue_job("remediate_file", {})
    release = isolated_store.enqueue_job("publish_file", {})

    monkeypatch.setenv("ACP_WORKER_ROLE", "assess")
    assess_types = core._worker_job_types(0, 2)
    assert isolated_store.claim_job("assess", job_types=assess_types)["id"] == assess
    assert isolated_store.get_job(remediation)["status"] == "queued"

    monkeypatch.setenv("ACP_WORKER_ROLE", "remediate")
    remediate_types = core._worker_job_types(0, 2)
    assert isolated_store.claim_job("remediate", job_types=remediate_types)["id"] == remediation
    assert isolated_store.claim_job("remediate", job_types=remediate_types)["id"] == release
    assert set(assess_types).isdisjoint(remediate_types)
