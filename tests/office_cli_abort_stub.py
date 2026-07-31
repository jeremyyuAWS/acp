"""A stand-in for AcpScan.Cli.dll that crashes on demand, for the SIGABRT regression.

Why a stub and not the real CLI. Production logged `[scan] office CLI exited -6` on both
.xlsx files of every run on 2026-07-30, with empty stderr and complete findings. That abort
does not reproduce on macOS with the real analysers — `demo-fixtures/excel-accessibility-demo.xlsx`
exits 0, cleanly, every time — because the crash is in .NET runtime shutdown inside the Linux
container, not in the rule sweep. Waiting for a native repro would leave the swallowing
untested, and the swallowing is the defect: what the pipeline does with a dead analyser is a
property of `api/scanner.py`, not of whatever killed it.

So this reproduces the SHAPE of the crash rather than its cause: a process that writes real
findings and then dies by SIGABRT. It is invoked through the scanner's own argv contract
(`<runtime> <cli> <inputDir> <outJsonPath>`, see `_analyse_office`) with `scanner.DOTNET`
pointed at the test interpreter, so the test exercises the real subprocess plumbing —
`returncode` really is negative, and the runtime really is a process that already exited.

`ACP_STUB_MODE` selects which of the four outcomes to produce; see MODES below. The three
abort modes are the three timings that matter, and they are NOT equivalent — AcpScan.Cli's
Program.cs writes its JSON in one `File.WriteAllText` after the whole loop, so *when* the
abort lands decides whether the output is complete, half-written, or absent.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time

MODES = (
    "clean",                  # exit 0 with output — the happy path must stay unchanged
    "abort_after_complete_write",   # PRODUCTION'S CASE: full findings, then SIGABRT at shutdown
    "abort_after_truncated_write",  # SIGABRT interrupting the write — output is unparseable
    "abort_before_write",           # SIGABRT mid-sweep — no output at all
    "write_then_hang",              # output written, then hangs — the timeout's version of the same
    "abort_with_dotnet_trace",      # as above, but with the trace .NET really prints — see below
    "abort_with_stdout_only",       # the same words, on stdout instead, and stderr left empty
)

# What the runtime actually writes when a managed exception goes unhandled. Reproduced at full
# length on purpose: the point of the head+tail clip is that this does not FIT in one window, and
# a test built on a three-line trace would pass under the old tail-only clip too and prove nothing.
#
# Shape and frame order are taken from a real production trace (2026-07-30, acp-worker): the
# exception header first, innermost frames next, `AnalyseAsync` and the two `Program.<Main>`
# frames last. That order is the bug — a tail window lands in the frames every time, and the
# header, which is the only part naming the defect, is always the first thing to fall off.
DOTNET_TRACE = (
    "Unhandled exception. System.ArgumentException: 'windows-1252' is not a supported encoding "
    "name. For information on defining a custom encoding, see the documentation for the "
    "Encoding.RegisterProvider method. (Parameter 'name')\n"
    + "".join(
        f"   at DocumentFormat.OpenXml.Packaging.OpenXmlPart.LoadPartRelationships{i}"
        f"(OpenXmlPackage openXmlPackage, String relationshipId, Boolean loadDependencies)\n"
        for i in range(24)
    )
    + "   at DigitalA11y.Analysers.DotNet.Docx.DocxAnalyser.AnalyseAsync(String filePath, "
      "String jobId, String fileId, String fileName, IEnumerable`1 disabledRuleIds)\n"
      "   at Program.<Main>$(String[] args) in /build/acp/spike/dotnet/AcpScan.Cli/Program.cs:line 25\n"
      "   at Program.<Main>(String[] args)\n"
)

# The identifying half, which `[-400:]` discarded on all 8 production crashes.
TRACE_HEAD_MARKER = "System.ArgumentException"
TRACE_MESSAGE_MARKER = "not a supported encoding name"
# The last frame, which `[-400:]` did keep — the head must not be bought by losing this.
TRACE_TAIL_MARKER = "Program.<Main>(String[] args)"

OFFICE_EXTS = (".docx", ".pptx", ".xlsx")

# Two findings of different severity, so a test can tell "findings were kept" from
# "findings were dropped" by score as well as by count.
ISSUES = [
    {"ruleId": "xlsx.sheet-name", "wcag": "1.3.1", "severity": "Serious",
     "title": "Worksheet still has its default name", "location": None},
    {"ruleId": "xlsx.merged-cells", "wcag": "1.3.1", "severity": "Moderate",
     "title": "Merged cells break reading order", "location": None},
]


def main() -> None:
    in_dir, out_path = sys.argv[1], sys.argv[2]
    mode = os.environ.get("ACP_STUB_MODE", "clean")
    if mode not in MODES:
        raise SystemExit(f"unknown ACP_STUB_MODE {mode!r}; expected one of {MODES}")

    # Report on exactly the office files present, the way the real CLI's loop does — so a test
    # that stages two files gets two results and can assert the per-file fan-out.
    results = [
        {"file": name, "succeeded": True, "errors": [], "issues": ISSUES}
        for name in sorted(os.listdir(in_dir))
        if name.lower().endswith(OFFICE_EXTS)
    ]
    text = json.dumps(results)

    if mode in ("clean", "abort_after_complete_write", "write_then_hang",
                "abort_with_dotnet_trace", "abort_with_stdout_only"):
        with open(out_path, "w") as fh:
            fh.write(text)
    elif mode == "abort_after_truncated_write":
        with open(out_path, "w") as fh:
            fh.write(text[: len(text) // 2])   # a write the abort cut in half

    if mode == "clean":
        return
    if mode == "abort_with_dotnet_trace":
        sys.stderr.write(DOTNET_TRACE)
        sys.stderr.flush()
    elif mode == "abort_with_stdout_only":
        # Not a hypothetical: #109 recorded EMPTY stderr for this crash. Whether that was the old
        # clip or a genuinely silent stderr, a diagnostic that only ever reads one stream cannot
        # tell those apart — so the scanner reads both, and this mode is what proves it.
        sys.stdout.write(DOTNET_TRACE)
        sys.stdout.flush()
    if mode == "write_then_hang":
        # subprocess.run's timeout kills us; sleep well past any timeout a test would set.
        time.sleep(3600)
        return
    # Not sys.exit(6): the bug is about a NEGATIVE returncode (killed by a signal), and an
    # exit status of 6 would be a different code path in _cli_exit_reason.
    os.kill(os.getpid(), signal.SIGABRT)


if __name__ == "__main__":
    main()
