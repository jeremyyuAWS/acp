"""ACP's provenance stamp has to survive the write, and every read path must ask for it.

Observed live: every discovery logs "0 skipped as ACP-generated output" even after remediating
a deck, so no file in Drive carries `properties.acpGenerated`. Two things could produce that —
the write never set the property, or the read never requested it — and nothing distinguished
them. These tests close the read side and make the write side say which.

The in-document content stamp still catches ACP's own output, so nothing here is load-bearing
for correctness. It is load-bearing for *knowing*.
"""
import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1] / "api"
sys.path.insert(0, str(API))

import provenance  # noqa: E402


# ── every Drive listing asks for `properties` ──

def _code(name: str) -> str:
    return "\n".join(l for l in (API / name).read_text().split("\n")
                     if not l.strip().startswith("#"))


def test_every_files_list_that_feeds_discovery_requests_the_stamp():
    """A `fields=` that omits `properties` makes is_acp_generated structurally unable to fire.

    Drive returns only the fields you name. Three listings feed discovery (whole-Drive, folder
    BFS, ADC pinned-folder); the third asked for `files(id,name,mimeType,md5Checksum)`, so its
    provenance filter could never match anything.
    """
    import re
    code = _code("scanner.py")
    # Every list() whose result is normalized into scan items must carry DRIVE_FIELDS.
    listings = re.findall(r"svc\.files\(\)\.list\((.*?)\)\.execute", code, re.S)
    feeding = [l for l in listings if "md5Checksum" in l or "DRIVE_FIELDS" in l]
    assert len(feeding) >= 3, f"expected the three discovery listings, found {len(feeding)}"
    for l in feeding:
        assert "provenance.DRIVE_FIELDS" in l, (
            "a discovery listing requests a hand-written field set instead of "
            f"provenance.DRIVE_FIELDS, so `properties` never returns: {l[:90]!r}")


def test_drive_fields_actually_contains_properties():
    # The guard above is worthless if the constant itself forgets the field.
    assert "properties" in provenance.DRIVE_FIELDS


def test_the_adc_branch_also_honours_exclude_remediated():
    code = _code("scanner.py")
    adc = code[code.index("_DEMO_FOLDER}' in parents"):]
    adc = adc[:adc.index("return _dedupe_names")]
    assert "exclude_remediated" in adc and "is_acp_generated" in adc


# ── the write verifies its own stamp ──

def test_the_mirror_asks_drive_to_echo_properties_back():
    code = _code("handlers.py")
    assert code.count('fields="id,webViewLink,properties"') == 2, \
        "both the create and the update path must request `properties` back"


def test_the_mirror_logs_when_the_stamp_does_not_round_trip():
    code = _code("handlers.py")
    assert "if not provenance.is_acp_generated(result):" in code
    assert "remediate.stamp_not_persisted" in code


def test_a_missing_stamp_never_fails_the_mirror():
    # Diagnostic only: the in-document content stamp still catches the copy, and Blob already
    # holds the durable output. Raising here would turn an observability gap into an outage.
    code = _code("handlers.py")
    block = code[code.index("if not provenance.is_acp_generated(result):"):]
    block = block[:block.index("core.store.record_remediation")]
    assert "raise" not in block


# ── is_acp_generated, against what Drive actually returns ──

def test_a_stamped_file_is_recognised():
    assert provenance.is_acp_generated(
        {"id": "1", "properties": {provenance.ACP_STAMP_KEY: provenance.ACP_STAMP_VALUE}})


@pytest.mark.parametrize("f", [
    {"id": "1"},                                   # Drive omits `properties` when there are none
    {"id": "1", "properties": {}},
    {"id": "1", "properties": {"other": "x"}},
    {"id": "1", "properties": {provenance.ACP_STAMP_KEY: "something-else"}},
    {},
])
def test_an_unstamped_file_is_never_mistaken_for_acp_output(f):
    # A false positive here DROPS a real source document from the estate — strictly worse than
    # re-ingesting ACP's own copy. The check must be exact.
    assert provenance.is_acp_generated(f) is False


def test_stamp_writes_the_key_the_reader_looks_for():
    props = provenance.stamp("deck.pptx")
    assert props[provenance.ACP_STAMP_KEY] == provenance.ACP_STAMP_VALUE
    assert provenance.is_acp_generated({"properties": props}) is True
