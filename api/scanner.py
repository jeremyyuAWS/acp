"""Reusable scan core: source -> engines -> rubric -> report dict.

Emits progress via a callback (phase / files_found / files_done / current) so the
control plane can stream live activity. Ephemeral working copies are deleted when the
scan finishes (the "documents never retained" guarantee).
"""
from __future__ import annotations
import io, json, os, shutil, subprocess, sys, tempfile, uuid
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


def _noop(_):
    pass


def _list(source: str) -> list[dict]:
    if source == "local":
        return [{"name": p.name, "path": str(p)} for p in sorted((ACP / "test-corpus/files").glob("*"))
                if p.suffix.lower() in OFFICE + (".pdf",)]
    import google.auth
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=SCOPES)
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    files = svc.files().list(q=f"'{FOLDER}' in parents and trashed=false",
                             fields="files(id,name)", pageSize=200, orderBy="name").execute().get("files", [])
    return [{"name": f["name"], "id": f["id"]} for f in files]


def _download(item: dict, dest: Path, cache: dict) -> None:
    out = dest / item["name"]
    if "path" in item:
        out.write_bytes(Path(item["path"]).read_bytes())
        return
    svc = cache.get("svc")
    if svc is None:
        import google.auth
        from googleapiclient.discovery import build
        creds, _ = google.auth.default(scopes=SCOPES)
        svc = cache["svc"] = build("drive", "v3", credentials=creds, cache_discovery=False)
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=item["id"]))
    done = False
    while not done:
        _, done = dl.next_chunk()
    out.write_bytes(buf.getvalue())


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


def run_scan(source: str = "local", progress=_noop) -> dict:
    rb = Rubric.load_active(ACP / "config")
    started = datetime.now(timezone.utc).isoformat()
    tmp = Path(tempfile.mkdtemp(prefix="acp-api-scan-"))
    try:
        progress({"phase": "connecting", "files_found": 0, "files_done": 0, "current": None})
        items = _list(source)
        n = len(items)
        progress({"phase": "discovering", "files_found": n, "files_done": 0, "current": None})

        cache = {}
        for i, it in enumerate(items):
            progress({"phase": "reading", "files_found": n, "files_done": i, "current": it["name"]})
            _download(it, tmp, cache)

        office = _analyse_office(tmp)
        raw: dict[str, dict] = {}
        for i, it in enumerate(items):
            name, ext = it["name"], Path(it["name"]).suffix.lower()
            progress({"phase": "analysing", "files_found": n, "files_done": i, "current": name})
            if ext == ".pdf":
                raw[name] = {"engine": "python/pdf", **_analyse_pdf(tmp / name)}
            elif ext in OFFICE:
                raw[name] = {"engine": ".net/office",
                             **office.get(name, {"succeeded": False, "issues": [], "errors": ["no engine result"]})}

        progress({"phase": "scoring", "files_found": n, "files_done": n, "current": None})
        assessed = {k: rb.assess(r["succeeded"], r["issues"], r["errors"]) for k, r in raw.items()}
        return {
            "rubric": {"name": rb.name, "version": rb.version, "hash": rb.hash},
            "summary": rb.aggregate(assessed),
            "started_at": started,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "files": [{"file": k, "engine": raw[k]["engine"], **assessed[k], "issues": raw[k]["issues"]}
                      for k in sorted(raw)],
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)  # ephemeral: documents never retained
