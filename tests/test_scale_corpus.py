"""The scale corpus is a scale test of the estate classifier, not just a data dump.

scripts/scale_corpus.generate() builds a synthetic Drive listing at UTSW shape and cross-checks its
by-construction intent against estate_inventory.summarize() — so a classifier that misbuckets a
format at scale fails inside generate(). These pin that it stays deterministic, self-consistent, and
shaped like a real content estate (a large unsupported blind spot, not an all-assessable fiction).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import estate_inventory as inv  # noqa: E402
import scale_corpus  # noqa: E402


def test_generator_cross_checks_the_classifier_and_is_self_consistent():
    # generate() asserts intent == summarize() internally; calling it validates the classifier at
    # scale. Here we re-assert the estate summary is self-consistent.
    files, folders, manifest = scale_corpus.generate(n=3000, seed=7)
    e = manifest["estate"]
    assert e["discovered"] == 3000                      # folders dropped from the discovered count
    assert len(files) == 3000 and len(folders) > 0
    assert sum(e["by_format"].values()) == 3000         # every file lands in exactly one format
    assert sum(e["by_status"].values()) == 3000         # …and exactly one status
    assert e["assessment_eligible"] == e["by_status"][inv.ASSESSABLE]


def test_generation_is_deterministic_for_a_seed():
    a = scale_corpus.generate(n=1500, seed=3)[2]["estate"]
    b = scale_corpus.generate(n=1500, seed=3)[2]["estate"]
    assert a == b                                       # same seed → identical estate summary


def test_estate_has_a_real_unsupported_blind_spot_not_an_all_assessable_fiction():
    _, _, manifest = scale_corpus.generate(n=4000, seed=11)
    e = manifest["estate"]
    assessable_pct = e["assessment_eligible"] / e["discovered"]
    blind_spot = (e["by_status"].get(inv.METADATA_ONLY, 0) + e["by_status"].get(inv.UNSUPPORTED, 0)) / e["discovered"]
    # A hospital estate is majority-but-not-all assessable, with a substantial metadata-only /
    # unsupported tail — the "unsupported ≠ passed" point the whole-estate view exists to make.
    assert 0.55 <= assessable_pct <= 0.70, assessable_pct
    assert blind_spot >= 0.25, blind_spot
    # Excluded (ACP's own output) exists and is NOT counted as assessment-eligible.
    assert e["by_status"].get(inv.EXCLUDED, 0) > 0


def test_manifest_carries_the_department_and_visibility_cuts_the_dashboard_needs():
    _, _, manifest = scale_corpus.generate(n=2000, seed=5)
    assert len(manifest["by_department"]) == len(scale_corpus.DEPARTMENTS)
    assert sum(manifest["by_department"].values()) == 2000
    assert set(manifest["by_visibility"]) <= {"public", "shared", "internal"}
    assert sum(manifest["by_visibility"].values()) == 2000
