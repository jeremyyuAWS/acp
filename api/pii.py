"""PII / sensitive-data detection over document text (ADR 0006).

A detection dimension orthogonal to WCAG accessibility. The scanner already
downloads each document to a temp file; this module extracts its text and flags
sensitive data with deterministic, *validated* detectors (SSN area/group rules,
credit-card Luhn checksum, IP octet ranges).

PRIVACY CONTRACT: this module NEVER returns or stores a raw PII value. Every
sample is masked (all but the last 4 characters), so neither the database nor
Langfuse ever holds a second copy of someone's SSN. See ADR 0006.

Text extraction uses only already-shipped libs — lxml (HTML), pdfplumber (PDF),
stdlib zipfile (OOXML) — so this adds no new dependency.
"""
from __future__ import annotations
import re
import zipfile
from pathlib import Path

# ── detectors ─────────────────────────────────────────────────────────────────
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN   = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
_CARD  = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_IPV4  = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")

# type -> (human label, severity)
_META = {
    "ssn":         ("Social Security numbers", "critical"),
    "credit_card": ("Credit-card numbers",     "critical"),
    "email":       ("Email addresses",         "moderate"),
    "phone":       ("Phone numbers",           "moderate"),
    "ip":          ("IP addresses",            "low"),
}
_SEV_RANK = {"critical": 3, "moderate": 2, "low": 1}


def _luhn(digits: str) -> bool:
    d = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(d) <= 19:
        return False
    total, alt = 0, False
    for x in reversed(d):
        if alt:
            x *= 2
            if x > 9:
                x -= 9
        total += x
        alt = not alt
    return total % 10 == 0


def _valid_ssn(area: str, group: str, serial: str) -> bool:
    # Reject structurally-invalid SSNs (never issued) to cut false positives.
    if area in ("000", "666") or area[0] == "9":
        return False
    return group != "00" and serial != "0000"


def _mask_tail(value: str, keep: int = 4) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) <= keep:
        return "•" * len(digits)
    return "•" * (len(digits) - keep) + digits[-keep:]


def _mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    head = local[0] if local else ""
    return f"{head}•••@{domain}"


# ── extraction ────────────────────────────────────────────────────────────────
def _html_text(path: Path) -> str:
    from lxml import html as lxml_html
    data = path.read_bytes()
    if not data.strip():
        return ""
    return lxml_html.fromstring(data).text_content()


def _ooxml_text(path: Path) -> str:
    """Text from a docx/pptx/xlsx by stripping XML tags from its body parts.
    Dependency-free (OOXML is a zip of XML) — good enough to find PII strings."""
    parts: list[str] = []
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith(".xml"):
                continue
            if name.startswith(("word/", "ppt/slides/", "xl/sharedStrings", "xl/worksheets")):
                xml = z.read(name).decode("utf-8", "ignore")
                parts.append(re.sub(r"<[^>]+>", " ", xml))
    return " ".join(parts)


def _pdf_text(path: Path) -> str:
    import pdfplumber
    out: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def extract_text(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    if ext in ("html", "htm"):
        return _html_text(path)
    if ext in ("docx", "pptx", "xlsx"):
        return _ooxml_text(path)
    if ext == "pdf":
        return _pdf_text(path)
    if ext in ("txt", "csv", "md", "json", "rtf", "xml"):
        return path.read_text("utf-8", "ignore")
    # Unknown: best-effort text read (binary returns mostly nothing useful).
    try:
        return path.read_text("utf-8", "ignore")
    except Exception:
        return ""


# ── detection ─────────────────────────────────────────────────────────────────
def detect_text(text: str) -> list[dict]:
    """Return one finding dict per PII type present, with MASKED samples only."""
    if not text:
        return []
    raw: dict[str, list[str]] = {}

    for m in _SSN.finditer(text):
        if _valid_ssn(*m.groups()):
            raw.setdefault("ssn", []).append(_mask_tail(m.group(0)))
    for m in _CARD.finditer(text):
        if _luhn(m.group(0)):
            raw.setdefault("credit_card", []).append(_mask_tail(m.group(0)))
    for m in _EMAIL.finditer(text):
        raw.setdefault("email", []).append(_mask_email(m.group(0)))
    for m in _PHONE.finditer(text):
        raw.setdefault("phone", []).append(_mask_tail(m.group(0)))
    for m in _IPV4.finditer(text):
        # Don't double-count an IP that is actually the local part of nothing;
        # keep the first three octets, mask the last.
        octets = m.group(0).rsplit(".", 1)
        raw.setdefault("ip", []).append(octets[0] + ".•••")

    findings: list[dict] = []
    for ptype, samples in raw.items():
        label, severity = _META[ptype]
        findings.append({
            "type": ptype,
            "label": label,
            "count": len(samples),
            "severity": severity,
            "samples": _dedupe(samples)[:5],   # cap stored masked samples
        })
    # Most severe first.
    findings.sort(key=lambda f: (_SEV_RANK[f["severity"]], f["count"]), reverse=True)
    return findings


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def detect_file(path: Path) -> dict:
    """Extract + detect for one document. Returns a summary dict (never raw PII)."""
    try:
        text = extract_text(path)
    except Exception as e:  # extraction is best-effort; never fail the scan over it
        return {"types": {}, "total": 0, "severity": None, "findings": [], "error": str(e)[:200]}
    findings = detect_text(text)
    total = sum(f["count"] for f in findings)
    severity = None
    for f in findings:
        if severity is None or _SEV_RANK[f["severity"]] > _SEV_RANK[severity]:
            severity = f["severity"]
    return {
        "types": {f["type"]: f["count"] for f in findings},
        "total": total,
        "severity": severity,
        "findings": findings,
    }


def summarize(findings: list[dict]) -> str:
    """One-line human summary, e.g. '3 SSNs, 2 credit-card numbers'."""
    bits = []
    for f in findings:
        n = f["count"]
        noun = f["label"].lower()
        if n == 1:
            noun = noun.rstrip("s") if noun.endswith("s") else noun
        bits.append(f"{n} {noun}")
    return ", ".join(bits)
