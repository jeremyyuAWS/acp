"""Tests for the PII detector (ADR 0006).

Focus on the two things that matter most: detectors are VALIDATED (low false
positives) and output is always MASKED (no raw PII ever leaves the module).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import pii  # noqa: E402


def _types(text):
    return {f["type"]: f for f in pii.detect_text(text)}


def test_valid_ssn_detected_and_masked():
    f = _types("Employee SSN: 123-45-6789 on file")["ssn"]
    assert f["count"] == 1
    assert f["severity"] == "critical"
    # masked: only last 4 digits survive
    assert f["samples"] == ["•••••6789"]
    assert "123-45-6789" not in str(f)


def test_invalid_ssn_rejected():
    # 000 area, 666 area, 9xx area, 00 group, 0000 serial are never issued
    assert "ssn" not in _types("000-12-3456 666-45-6789 900-45-6789 123-00-6789 123-45-0000")


def test_credit_card_luhn_validated():
    # 4111 1111 1111 1111 is the canonical Luhn-valid Visa test number
    f = _types("Card 4111 1111 1111 1111 charged")["credit_card"]
    assert f["count"] == 1
    assert f["samples"] == ["••••••••••••1111"]


def test_credit_card_luhn_rejects_bad_number():
    # one digit off → fails Luhn → not flagged
    assert "credit_card" not in _types("Card 4111 1111 1111 1112 declined")


def test_email_and_phone_masked():
    t = _types("Reach jane.doe@example.com or (415) 555-0142")
    assert t["email"]["samples"] == ["j•••@example.com"]
    assert t["email"]["severity"] == "moderate"
    assert t["phone"]["count"] == 1
    assert "555-0142" not in str(t["phone"]) or t["phone"]["samples"][0].endswith("0142")
    assert t["phone"]["samples"][0].startswith("•")


def test_ip_octet_validation():
    t = _types("server 10.0.0.5 not 999.1.1.1")
    assert t["ip"]["count"] == 1
    assert t["ip"]["samples"] == ["10.0.0.•••"]


def test_no_pii_returns_empty():
    assert pii.detect_text("A perfectly ordinary sentence with no secrets.") == []


def test_detect_file_html(tmp_path):
    p = tmp_path / "leak.html"
    p.write_text("<html><body><p>SSN 123-45-6789, card 4111111111111111</p></body></html>")
    info = pii.detect_file(p)
    assert info["total"] == 2
    assert info["severity"] == "critical"
    assert info["types"] == {"ssn": 1, "credit_card": 1}
    # ensure no raw values anywhere in the returned structure
    blob = str(info)
    assert "123-45-6789" not in blob and "4111111111111111" not in blob


def test_detect_file_text_dedupes_samples(tmp_path):
    p = tmp_path / "list.txt"
    p.write_text("\n".join(["a@b.com"] * 10))
    info = pii.detect_file(p)
    # 10 occurrences counted, but masked samples deduped + capped
    assert info["types"]["email"] == 10
    assert len(info["findings"][0]["samples"]) == 1


def test_summarize_pluralization():
    findings = pii.detect_text("123-45-6789 and a@b.com")
    s = pii.summarize(findings)
    assert "1 social security number" in s
    assert "1 email address" in s
