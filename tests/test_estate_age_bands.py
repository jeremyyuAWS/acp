"""Age distribution over the estate — counted over every file, not over the capped sample.

`modified` has been in this module all along, but only inside `_sample_meta`, which fills at most
`sample_per_status` rows per status. A histogram built from that would be a picture of ≤200 files
per bucket presented as the whole estate: plausible shape, confident bars, wrong denominator. It is
the failure this module's own header names — "unsupported reads as passed by omission" — wearing a
different hat, so the bands are aggregated in `summarize` over the full listing.

Guarded here:

  · the bands reconcile with `discovered`, so a reader can add them up and get the total
  · a file with no usable timestamp is COUNTED as unknown, never folded into a band or dropped
  · boundaries are exact and tested against an INJECTED `now` — a distribution that reads the wall
    clock is one whose tests pass until they do not, which is exactly how a frontend date assertion
    in this repo broke the day after it was written
  · a future timestamp lands in the youngest band rather than becoming "unknown"
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from estate_inventory import (  # noqa: E402
    AGE_BANDS, AGE_UNKNOWN, age_band, summarize,
)

NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


def _at(days_ago: int) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def _f(name: str, days_ago: int | None, mime: str = "application/pdf") -> dict:
    f = {"id": name, "name": name, "mimeType": mime}
    if days_ago is not None:
        f["modifiedTime"] = _at(days_ago)
    return f


# ── the banding function itself ───────────────────────────────────────────────────────────────

def test_each_band_gets_its_own_file():
    assert age_band(_at(10), NOW) == "lt_1y"
    assert age_band(_at(500), NOW) == "y1_3"
    assert age_band(_at(1200), NOW) == "y3_5"
    assert age_band(_at(4000), NOW) == "gt_5y"


def test_the_boundaries_are_exact():
    """Off-by-one here moves files between "keep" and "delete" advice."""
    assert age_band(_at(364), NOW) == "lt_1y"
    assert age_band(_at(365), NOW) == "y1_3"      # the boundary belongs to the OLDER band
    assert age_band(_at(1094), NOW) == "y1_3"
    assert age_band(_at(1095), NOW) == "y3_5"
    assert age_band(_at(1824), NOW) == "y3_5"
    assert age_band(_at(1825), NOW) == "gt_5y"


def test_a_missing_or_unparseable_timestamp_is_unknown_not_a_guess():
    for bad in (None, "", "not-a-date", 12345, "2026-13-45T99:00:00Z"):
        assert age_band(bad, NOW) == AGE_UNKNOWN


def test_a_future_timestamp_lands_in_the_youngest_band():
    """Clock skew on the source, or a mis-set date. A real file with an implausible date is still a
    real file — 'unknown' would hide it from a distribution it belongs in."""
    future = (NOW + timedelta(days=30)).isoformat().replace("+00:00", "Z")
    assert age_band(future, NOW) == "lt_1y"


def test_a_naive_timestamp_is_read_as_utc_rather_than_rejected():
    assert age_band("2026-08-19T10:00:00", NOW) == "lt_1y"


# ── the aggregate ─────────────────────────────────────────────────────────────────────────────

def test_bands_are_counted_over_every_file_not_the_sample():
    """THE case. With a sample cap of 2, a sample-derived histogram would report 2 per status."""
    files = [_f(f"old{i}.pdf", 4000) for i in range(50)]
    out = summarize(files, sample_per_status=2, now=NOW)
    assert out["discovered"] == 50
    assert out["by_age"]["gt_5y"] == 50, "the age histogram was built from the capped sample"
    # And the cap really is in force, so the assertion above is not passing by accident.
    assert len(out["samples"]["assessable"]) == 2


def test_the_bands_sum_to_discovered():
    """A reader must be able to add them up. That is why unknown is counted rather than dropped."""
    files = [
        _f("a.pdf", 10), _f("b.docx", 500), _f("c.pptx", 1200), _f("d.xlsx", 4000),
        _f("e.pdf", None), _f("f.mov", 4000, "video/quicktime"),
    ]
    out = summarize(files, now=NOW)
    assert sum(out["by_age"].values()) == out["discovered"] == 6


def test_files_with_no_timestamp_are_visible_as_unknown():
    out = summarize([_f("a.pdf", None), _f("b.pdf", 10)], now=NOW)
    assert out["by_age"][AGE_UNKNOWN] == 1
    assert out["by_age"]["lt_1y"] == 1


def test_unsupported_and_metadata_only_files_are_banded_too():
    """Age is a RETENTION question, so it spans the whole estate — not just what ACP can assess.
    An old .mov nobody has opened in five years is exactly the delete candidate this is for."""
    out = summarize([_f("clip.mov", 4000, "video/quicktime"), _f("x.zip", 4000, "application/zip")],
                    now=NOW)
    assert out["by_age"]["gt_5y"] == 2
    assert out["assessment_eligible"] == 0


def test_one_now_is_used_for_the_whole_listing():
    """Reading the clock per file would let a long scan straddle a boundary and produce counts that
    no longer reconcile. Pinned by banding a file that sits exactly ON the boundary alongside many
    others: with a per-file clock the run would split across two bands.
    """
    files = [_f(f"x{i}.pdf", 365) for i in range(200)]
    out = summarize(files, now=NOW)
    assert out["by_age"] == {"y1_3": 200}


def test_an_empty_estate_yields_no_bands_rather_than_zeros():
    out = summarize([], now=NOW)
    assert out["by_age"] == {}
    assert out["discovered"] == 0


def test_band_keys_are_the_declared_ones():
    """Guards against a band key drifting away from AGE_BANDS, which would leave a consumer
    rendering a bucket it has no label for."""
    files = [_f("a.pdf", 10), _f("b.pdf", 500), _f("c.pdf", 1200), _f("d.pdf", 4000), _f("e.pdf", None)]
    out = summarize(files, now=NOW)
    known = {k for k, _label, _u in AGE_BANDS} | {AGE_UNKNOWN}
    assert set(out["by_age"]) <= known
