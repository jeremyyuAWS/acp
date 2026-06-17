"""Track-A first scan: read acp-demo-corpus from Drive -> run engines -> score -> diff oracle.

Dispatches PDFs to devSEAL's PdfAnalyser (in-process) and Office files to the .NET
scan CLI, then compares findings to test-corpus/manifest.json (the ground-truth oracle)
and prints a smoke-test report + bug list.

Run with the prepared venv:
  ~/projects/acp/.venv-drive/bin/python scripts/scan.py
"""
from __future__ import annotations
import asyncio, io, json, os, subprocess, sys, tempfile, uuid
from datetime import datetime, timezone
from pathlib import Path

import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import result_model as rm

FOLDER = "1W27ULZsstP7gYGzgKKBId0qEfNxeKn0_"
ACP = Path(__file__).resolve().parent.parent
WP = Path(os.path.expanduser("~/projects/_review-digital-accessibility/worker-python"))
DOTNET = os.path.expanduser("~/.dotnet/dotnet")
CLI = ACP / "spike/dotnet/AcpScan.Cli"

# ── 1. download the corpus from Drive (keyless ADC) ──────────────────────────
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
svc = build("drive", "v3", credentials=creds, cache_discovery=False)
files = svc.files().list(q=f"'{FOLDER}' in parents and trashed=false",
                         fields="files(id,name)", pageSize=100, orderBy="name").execute().get("files", [])
tmp = Path(tempfile.mkdtemp(prefix="acp-scan-"))
for f in files:
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, svc.files().get_media(fileId=f["id"]))
    done = False
    while not done:
        _, done = dl.next_chunk()
    (tmp / f["name"]).write_bytes(buf.getvalue())
print(f"downloaded {len(files)} files from acp-demo-corpus -> {tmp}\n")

results: dict[str, dict] = {}

# ── 2. PDFs via devSEAL PdfAnalyser (unchanged) ──────────────────────────────
sys.path.insert(0, str(WP))
from analysers.pdf_analyser import PdfAnalyser
from models.manifest import AnalysisJob, FileType

def job(path):
    return AnalysisJob(job_id=uuid.uuid4(), batch_run_id=uuid.uuid4(), file_id=uuid.uuid4(),
                       file_path=str(path), file_type=FileType.PDF, queue="pdf",
                       enqueued_at=datetime.now(timezone.utc), department_id=uuid.uuid4(),
                       disabled_rule_ids=[])
pdf = PdfAnalyser()
for path in sorted(tmp.glob("*.pdf")):
    try:
        r = asyncio.run(pdf.analyse(path, job(path)))
        results[path.name] = {
            "engine": "python/pdf", "succeeded": r.succeeded,
            "issues": [{"ruleId": i.rule_id, "wcag": i.wcag_criterion.name, "severity": i.severity.name} for i in r.issues],
            "errors": [e.message for e in r.errors],
        }
    except Exception as e:
        results[path.name] = {"engine": "python/pdf", "succeeded": False, "issues": [], "errors": [f"{type(e).__name__}: {e}"]}

# ── 3. Office via the .NET scan CLI ──────────────────────────────────────────
out_json = tmp / "_office.json"
env = {**os.environ, "DOTNET_ROOT": os.path.expanduser("~/.dotnet"),
       "PATH": os.path.expanduser("~/.dotnet") + ":" + os.environ.get("PATH", ""),
       "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
proc = subprocess.run([DOTNET, "run", "--project", str(CLI), "-c", "Release", "--", str(tmp), str(out_json)],
                      capture_output=True, text=True, env=env)
if out_json.exists():
    for item in json.loads(out_json.read_text()):
        results[item["file"]] = {
            "engine": ".net/office", "succeeded": item["succeeded"],
            "issues": [{"ruleId": i["ruleId"], "wcag": i["wcag"], "severity": i["severity"]} for i in item["issues"]],
            "errors": [(e.get("message") or e.get("Message") or str(e)) for e in item["errors"]],
        }
else:
    print("!! .NET CLI produced no output:\n", proc.stdout[-800:], proc.stderr[-800:])

# ── 4. assess (status/score) + compliance gate + oracle diff ─────────────────
oracle = {m["file"]: m for m in json.loads((ACP / "test-corpus/manifest.json").read_text())}
print(f"{'file':24} {'engine':12} {'status':10} {'score':>30}  findings")
print("-" * 100)
certifiable = uncertain = errored = 0
for name in sorted(results):
    r = results[name]
    a = rm.assess(r["succeeded"], r["issues"], r["errors"])
    certifiable += a["compliant"]
    uncertain += a["status"] == "uncertain"
    errored += a["status"] == "error"
    rules = sorted({i["ruleId"] for i in r["issues"]})
    detail = ",".join(rules) if rules else (r["errors"][0][:34] if r["errors"] else "clean")
    print(f"{name:24} {r['engine']:12} {a['status']:10} {rm.render_score(a):>30}  {detail}")

print("\n=== compliance gate (the Track-A fix in action) ===")
print(f"  certifiable-clean: {certifiable}    uncertain (rule skipped): {uncertain}    error (unanalysable): {errored}")
print("  → only fully-analysed files can be certified; 'uncertain' and 'error' are NOT passes.")

# oracle diff: status vs expected outcome (all files); exact rule ids (docx only)
bugs = []
for name in sorted(results):
    r = results[name]
    m = oracle.get(name, {})
    a = rm.assess(r["succeeded"], r["issues"], r["errors"])
    got = "error" if a["status"] == "error" else "analysed"
    exp = m.get("expected_outcome", "?")
    if got != exp:
        bugs.append(f"{name}: expected '{exp}' but got '{got}'")
    exp_rules = set(m.get("expected_rule_ids", []))
    if exp == "analysed" and exp_rules and name.startswith("docx"):
        rules = {i["ruleId"] for i in r["issues"]}
        miss, extra = exp_rules - rules, rules - exp_rules
        if miss or extra:
            bugs.append(f"{name}: rule mismatch missing={sorted(miss)} extra={sorted(extra)}")
print("\n=== oracle diff ===")
print("\n".join("  ✗ " + b for b in bugs) if bugs else "  ✓ no deviations on exact checks")
