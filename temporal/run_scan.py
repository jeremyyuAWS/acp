"""Kick off the durable scan workflow and print the result."""
import asyncio
import json
import sys
from pathlib import Path

from temporalio.client import Client

from workflow import ScanWorkflow

TASK_QUEUE = "acp-scan"


async def main():
    wf_id = sys.argv[1] if len(sys.argv) > 1 else "acp-scan-demo"
    client = await Client.connect("localhost:7233")
    rep = await client.execute_workflow(ScanWorkflow.run, id=wf_id, task_queue=TASK_QUEUE)

    s = rep["summary"]
    print(f"\n=== Temporal scan complete · {s['rubric']} · rubric_hash={s['rubric_hash']} ===")
    print(f"  files={s['files']}  certifiable={s['certifiable']}  "
          f"uncertain={s['uncertain']}  error={s['error']}  avg_score={s['avg_score']}\n")
    for f in sorted(rep["files"], key=lambda x: x["file"]):
        print(f"  {f['file']:24} {f['status']:10} score={f['score']}")
    out = Path(__file__).resolve().parent.parent / "test-corpus/last-scan-temporal.json"
    out.write_text(json.dumps(rep, indent=2))
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
