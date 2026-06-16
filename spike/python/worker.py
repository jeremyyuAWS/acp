"""
acp derisk spike — wrap devSEAL's UNCHANGED PdfAnalyser as a Temporal Python activity.

Proves the Python half of Phase 1's engine seam: Temporal Python SDK worker +
their pikepdf/pdfplumber engine as an activity + the A11yIssue contract crossing
the Temporal boundary (as plain JSON dicts -> no custom data converter needed).

  1. temporal server start-dev          (local Temporal on :7233)
  2. uv run --with temporalio --with pikepdf --with pdfplumber --with pydantic \
         --with pypdfium2 python worker.py <path-to.pdf>

Their analysis functions are called AS-IS (no edits to their code).
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# Put the devSEAL worker-python tree on the path so we import their UNCHANGED engine.
WORKER_PY = Path.home() / "projects" / "_review-digital-accessibility" / "worker-python"
sys.path.insert(0, str(WORKER_PY))

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker

# pikepdf/pdfplumber are non-deterministic native libs — keep them out of the
# workflow sandbox; they only actually run inside the activity anyway.
with workflow.unsafe.imports_passed_through():
    from analysers.pdf_analyser import PdfAnalyser
    from models.manifest import AnalysisJob, AnalyserResult, FileType, IssueSeverity, WcagCriterion

TASK_QUEUE = "web-pdf"


@activity.defn
async def analyse_pdf(payload: dict) -> dict:
    """The wrapper: build their AnalysisJob, call their unchanged analyse(), return JSON."""
    job = AnalysisJob(
        job_id=uuid4(),
        batch_run_id=uuid4(),
        file_id=uuid4(),
        file_path=payload["file_path"],
        file_type=FileType.PDF,
        queue=TASK_QUEUE,
        enqueued_at=datetime.now(timezone.utc),
        department_id=uuid4(),
        disabled_rule_ids=payload.get("disabled_rule_ids", []),
    )
    result: AnalyserResult = await PdfAnalyser().analyse(Path(payload["file_path"]), job)
    return result.model_dump(by_alias=True, mode="json")


@workflow.defn
class ScanPdfWorkflow:
    @workflow.run
    async def run(self, payload: dict) -> dict:
        return await workflow.execute_activity(
            analyse_pdf, payload, start_to_close_timeout=timedelta(minutes=2)
        )


async def main() -> None:
    file_path = str(Path(sys.argv[1]).resolve())
    client = await Client.connect("localhost:7233")
    print(f"connected to Temporal; analysing {Path(file_path).name} via task queue '{TASK_QUEUE}'")

    async with Worker(client, task_queue=TASK_QUEUE, workflows=[ScanPdfWorkflow], activities=[analyse_pdf]):
        result = await client.execute_workflow(
            ScanPdfWorkflow.run, {"file_path": file_path},
            id=f"scan-pdf-{uuid4().hex}", task_queue=TASK_QUEUE,
        )

    print(json.dumps(result, indent=2)[:1500])
    issues = result.get("issues", [])
    print(f"\n✔ succeeded={result.get('succeeded')}  issues={len(issues)}  errors={len(result.get('errors', []))}")
    for i in issues:
        sev = IssueSeverity(i["severity"]).name
        sc = WcagCriterion(i["wcagCriterion"]).name
        print(f"  - [{sev}] {i['ruleId']} ({sc}) — {i['title']}")


if __name__ == "__main__":
    asyncio.run(main())
