"""Reusable scan core: source -> engines -> rubric -> report dict.

Shared by the CLI and the API. Source is 'local' (the bundled corpus) or 'drive'
(read acp-demo-corpus via keyless ADC). Returns the same report shape the dashboards
consume. The real app runs this as a Temporal workflow; here it runs in-process.
"""
from __future__ import annotations
import io, json, os, subprocess, sys, tempfile, uuid
from datetime import datetime, timezone
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
WP = Path(os.path.expanduser("~/projects/_review-digital-accessibility/worker-python"))
DOTNET = os.path.expanduser("~/.dotnet/dotnet")
CLI_DLL = ACP / "spike/dotnet/AcpScan.Cli/bin/Release/net10.0/AcpScan.Cli.dll"
FOLDER = "1W27ULZsstP7gYGzgKKBId0qEfNxeKn0_"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

sys.path.insert(0, str(ACP / "scripts"))
from rubric import Rubric

OFFICE = (".docx", ".pptx", ".xlsx")


def _fetch(source: str, dest: Path) -> list[str]:
    if source == "local":
        for p in (ACP / "test-corpus/files").glob("*"):
            if p.suffix.lower() in OFFICE + (".pdf",):
                (dest / p.name).write_bytes(p.read_bytes())
        return sorted(p.name for p in dest.iterdir())
    import google.auth
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    creds, _ = google.auth.default(scopes=SCOPES)
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    files = svc.files().list(q=f"'{FOLDER}' in parents and trashed=false",
                             fields="files(id,name)", pageSize=100, orderBy="name").execute().get("files", [])
    for f in files:
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=f["id"]))
        done = False
        while not done:
            _, done = dl.next_chunk()
        (dest / f["name"]).write_bytes(buf.getvalue())
    return sorted(f["name"] for f in files)


def _analyse_pdf(path: Path) -> dict:
    import asyncio
    sys.path.insert(0, str(WP))
    from analysers.pdf_analyser import PdfAnalyser
    from models.manifest import AnalysisJob, FileType
    job = AnalysisJob(job_id=uuid.uuid4(), batch_run_id=uuid.uuid4(), file_id=uuid.uuid4(),
                      file_path=str(path), file_type=FileType.PDF, queue="pdf",
                      enqueued_at=datetime.now(timezone.utc), department_id=uuid.uuid4(), disabled_rule_ids=[])
    try:
        r = asyncio.run(PdfAnalyser().analyse(path, job))
        return {"succeeded": r.succeeded,
                "issues": [{"ruleId": i.rule_id, "wcag": i.wcag_criterion.name, "severity": i.severity.name} for i in r.issues],
                "errors": [e.message for e in r.errors]}
    except Exception as e:
        return {"succeeded": False, "issues": [], "errors": [f"{type(e).__name__}: {e}"]}


def _analyse_office(dest: Path) -> dict:
    out = dest / "_o.json"
    env = {**os.environ, "DOTNET_ROOT": os.path.expanduser("~/.dotnet"),
           "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    subprocess.run([DOTNET, str(CLI_DLL), str(dest), str(out)], capture_output=True, text=True, env=env)
    res = {}
    if out.exists():
        for item in json.loads(out.read_text()):
            res[item["file"]] = {
                "succeeded": item["succeeded"],
                "issues": [{"ruleId": i["ruleId"], "wcag": i["wcag"], "severity": i["severity"]} for i in item.get("issues", [])],
                "errors": [(e.get("message") or e.get("Message") or str(e)) for e in item.get("errors", [])],
            }
    return res


def run_scan(source: str = "local") -> dict:
    rb = Rubric.load(ACP / "config/rubric.default.json")
    started = datetime.now(timezone.utc).isoformat()
    tmp = Path(tempfile.mkdtemp(prefix="acp-api-scan-"))
    names = _fetch(source, tmp)

    office = _analyse_office(tmp)
    raw: dict[str, dict] = {}
    for name in names:
        ext = Path(name).suffix.lower()
        if ext == ".pdf":
            raw[name] = {"engine": "python/pdf", **_analyse_pdf(tmp / name)}
        elif ext in OFFICE:
            raw[name] = {"engine": ".net/office",
                         **office.get(name, {"succeeded": False, "issues": [], "errors": ["no engine result"]})}

    assessed = {n: rb.assess(r["succeeded"], r["issues"], r["errors"]) for n, r in raw.items()}
    return {
        "rubric": {"name": rb.name, "version": rb.version, "hash": rb.hash},
        "summary": rb.aggregate(assessed),
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "files": [{"file": n, "engine": raw[n]["engine"], **assessed[n], "issues": raw[n]["issues"]}
                  for n in sorted(raw)],
    }
