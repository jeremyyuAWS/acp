"""Temporal activities for the acp scan: discover Drive files, analyse one file
(PDF via devSEAL PdfAnalyser, Office via the .NET CLI), score via the rubric.

Activities run outside the workflow sandbox, so heavy imports / I/O live here.
"""
from __future__ import annotations
import io, json, os, shutil, subprocess, sys, tempfile, uuid
from datetime import datetime, timezone
from pathlib import Path

from temporalio import activity
import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

FOLDER = "1W27ULZsstP7gYGzgKKBId0qEfNxeKn0_"
ACP = Path(__file__).resolve().parent.parent
WP = Path(os.path.expanduser("~/projects/_review-digital-accessibility/worker-python"))
DOTNET = os.path.expanduser("~/.dotnet/dotnet")
CLI_DLL = ACP / "spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _drive():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


@activity.defn
async def discover() -> list:
    svc = _drive()
    fs = svc.files().list(q=f"'{FOLDER}' in parents and trashed=false",
                          fields="files(id,name)", pageSize=100, orderBy="name").execute().get("files", [])
    activity.logger.info(f"discovered {len(fs)} files")
    return [{"id": f["id"], "name": f["name"]} for f in fs]


@activity.defn
async def analyse(file: dict) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="acp-act-"))
    try:
        return await _analyse(file, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # ephemeral: document copy deleted after analysis


async def _analyse(file: dict, tmp: Path) -> dict:
    svc = _drive()
    path = tmp / file["name"]
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=file["id"]))
    done = False
    while not done:
        _, done = dl.next_chunk()
    path.write_bytes(buf.getvalue())
    ext = path.suffix.lower()

    if ext == ".pdf":
        sys.path.insert(0, str(WP))
        from analysers.pdf_analyser import PdfAnalyser
        from models.manifest import AnalysisJob, FileType
        job = AnalysisJob(job_id=uuid.uuid4(), batch_run_id=uuid.uuid4(), file_id=uuid.uuid4(),
                          file_path=str(path), file_type=FileType.PDF, queue="pdf",
                          enqueued_at=datetime.now(timezone.utc), department_id=uuid.uuid4(),
                          disabled_rule_ids=[])
        try:
            r = await PdfAnalyser().analyse(path, job)
            return {"file": file["name"], "engine": "python/pdf", "succeeded": r.succeeded,
                    "issues": [{"ruleId": i.rule_id, "wcag": i.wcag_criterion.name, "severity": i.severity.name} for i in r.issues],
                    "errors": [e.message for e in r.errors]}
        except Exception as e:
            return {"file": file["name"], "engine": "python/pdf", "succeeded": False,
                    "issues": [], "errors": [f"{type(e).__name__}: {e}"]}

    if ext in (".docx", ".pptx", ".xlsx"):
        out = tmp / "_o.json"
        env = {**os.environ, "DOTNET_ROOT": os.path.expanduser("~/.dotnet"),
               "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
        subprocess.run([DOTNET, str(CLI_DLL), str(tmp), str(out)], capture_output=True, text=True, env=env)
        item = (json.loads(out.read_text())[0] if out.exists()
                else {"succeeded": False, "issues": [], "errors": [{"message": "cli produced no output"}]})
        return {"file": file["name"], "engine": ".net/office", "succeeded": item["succeeded"],
                "issues": [{"ruleId": i["ruleId"], "wcag": i["wcag"], "severity": i["severity"]} for i in item.get("issues", [])],
                "errors": [(e.get("message") or e.get("Message") or str(e)) for e in item.get("errors", [])]}

    return {"file": file["name"], "engine": "skip", "succeeded": True, "issues": [], "errors": []}


@activity.defn
async def score(raw: list) -> dict:
    sys.path.insert(0, str(ACP / "scripts"))
    from rubric import Rubric
    rb = Rubric.load(ACP / "config/rubric.default.json")
    assessed = {r["file"]: rb.assess(r["succeeded"], r["issues"], r["errors"]) for r in raw}
    return {
        "rubric": {"name": rb.name, "version": rb.version, "hash": rb.hash},
        "summary": rb.aggregate(assessed),
        "files": [{"file": r["file"], "engine": r["engine"], **assessed[r["file"]],
                   "issues": r["issues"]} for r in raw],
    }
