"""veraPDF availability gate and result parser, so PDF/UA claims rest on the real validator.

WHY THIS EXISTS SEPARATELY FROM engines.py. That module gates the two ANALYSIS engines ACP
ships. veraPDF is a third-party VALIDATOR we hold our own output to — the automated half of
ADR 0034's gate — and it is the only thing in this repo that can answer "is this PDF actually
PDF/UA-1 conformant". Passing ACP's own `TaggedPdfRule` does not: that rule asks whether a
structure tree exists, which is exactly the question a faked tree answers too.

NOT INSTALLED BY THE SUITE, and deliberately not vendored: it is a 33 MB Java application. Tests
that need it skip with a reason naming what is missing, the same discipline engines.py applies to
the Office CLI. Install it where you want the gate to run:

    curl -sSLo /tmp/verapdf.zip https://software.verapdf.org/releases/verapdf-installer.zip
    (cd /tmp && unzip -q verapdf.zip && cd verapdf-greenfield-*/ \\
       && java -jar verapdf-izpack-installer-*.jar /path/to/auto-install.xml)

`ACP_VERAPDF` overrides the location. Requires a JRE — veraPDF 1.30 runs on Java 21.

READ THE PARSED RESULT, NOT THE EXIT CODE. `verapdf` exits non-zero both for "the file is not
compliant" and for "the file could not be read", and a test that treats those alike reports a
broken fixture as a conformance finding. `validate()` distinguishes them: a run that never
produced a validation report raises, and non-compliance comes back as a Result with the failing
clauses named.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT = Path("/opt/verapdf/verapdf")
VERAPDF = Path(os.environ.get("ACP_VERAPDF") or _DEFAULT)

VERAPDF_OK: bool = VERAPDF.exists() or shutil.which("verapdf") is not None
NO_VERAPDF = (
    f"veraPDF not found at {VERAPDF} (set ACP_VERAPDF, or install from "
    f"https://software.verapdf.org/releases/verapdf-installer.zip — needs a JRE)"
)


@dataclass
class Failure:
    """One failed rule of the profile, identified the way the spec identifies it."""
    clause: str
    test_number: str
    failed_checks: int
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.clause}-{self.test_number}"

    def __str__(self) -> str:  # pragma: no cover - diagnostics only
        return f"clause {self.clause} test {self.test_number} ({self.failed_checks} failed)"


@dataclass
class Result:
    compliant: bool
    passed_checks: int
    failed_checks: int
    failures: list[Failure] = field(default_factory=list)

    @property
    def failure_keys(self) -> set[str]:
        return {f.key for f in self.failures}

    def summary(self) -> str:
        if self.compliant:
            return f"PASS ({self.passed_checks} checks)"
        return (f"FAIL ({self.failed_checks} failed / {self.passed_checks} passed): "
                + "; ".join(str(f) for f in self.failures))


def _binary() -> str:
    return str(VERAPDF) if VERAPDF.exists() else "verapdf"


def validate(path: str | Path, flavour: str = "ua1", timeout: int = 180) -> Result:
    """Validate one PDF against a veraPDF profile. Raises when veraPDF could not judge it.

    `flavour` is a veraPDF profile id — "ua1" is PDF/UA-1 (ISO 14289-1).
    """
    proc = subprocess.run(
        [_binary(), "-f", flavour, "--format", "mrr", str(path)],
        capture_output=True, timeout=timeout,
    )
    try:
        root = ET.fromstring(proc.stdout.decode("utf-8", "replace"))
    except ET.ParseError as exc:
        raise RuntimeError(
            f"veraPDF produced no parseable report for {path} "
            f"(exit {proc.returncode}): {proc.stderr.decode('utf-8', 'replace')[:400]}"
        ) from exc

    report = next((e for e in root.iter() if e.tag.endswith("validationReport")), None)
    if report is None:
        raise RuntimeError(
            f"veraPDF ran but produced no validationReport for {path} — the file could not be "
            f"read as a PDF, which is a broken fixture, not a conformance finding "
            f"(exit {proc.returncode})"
        )

    details = next((e for e in root.iter() if e.tag.endswith("details")), None)
    passed = int((details.get("passedChecks") if details is not None else 0) or 0)
    failed = int((details.get("failedChecks") if details is not None else 0) or 0)

    failures: list[Failure] = []
    for rule in root.iter():
        if not rule.tag.endswith("rule") or rule.get("status") != "failed":
            continue
        desc = ""
        for child in rule:
            if child.tag.endswith("description"):
                desc = (child.text or "").strip()
                break
        failures.append(Failure(
            clause=rule.get("clause", "?"),
            test_number=rule.get("testNumber", "?"),
            failed_checks=int(rule.get("failedChecks") or 0),
            description=desc,
        ))

    return Result(
        compliant=(report.get("isCompliant") == "true"),
        passed_checks=passed,
        failed_checks=failed,
        failures=sorted(failures, key=lambda f: (f.clause, f.test_number)),
    )
