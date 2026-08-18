"""Assessment accuracy at scale: the labeled corpus, embedded in the 30k estate.

Assessment is per-file and isolated, so DETECTION accuracy is scale-invariant (scanning a file
alone or among 30k is the same scan). What scale can break is DISCOVERY + ATTRIBUTION: are the
labeled files found among the estate, unique, assessable, with their labels intact. These pin that
metadata layer (engine-free). The actual per-file scoring reuses score_assessment and runs where
the analyser engine exists (scripts/scale_accuracy.score_located, exercised by the CLI/CI).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import estate_inventory as inv  # noqa: E402
import scale_accuracy as sa  # noqa: E402

ENTRIES = [
    {"filename": "complex-docx-many-issues.docx", "format": "docx",
     "injected_by_sc": {"1.1.1": 3, "1.3.1": 5, "1.4.3": 2}, "not_seeded": {"4.1.2": "no AcroForm"}},
    {"filename": "complex-xlsx-many-issues.xlsx", "format": "xlsx",
     "injected_by_sc": {"1.4.1": 2, "2.4.4": 4}, "not_seeded": {}},
    {"filename": "complex-pptx-many-issues.pptx", "format": "pptx",
     "injected_by_sc": {"1.1.1": 6}, "not_seeded": {}},
    {"filename": "complex-pdf-many-issues.pdf", "format": "pdf",
     "injected_by_sc": {"1.1.1": 4, "2.4.2": 1}, "not_seeded": {}},
]


def test_labeled_records_are_assessable_and_carry_their_labels():
    recs = sa.labeled_records(ENTRIES)
    assert len(recs) == 4
    for rec, e in zip(recs, ENTRIES):
        assert rec["_ground_truth"] is True
        assert rec["name"] == e["filename"]
        assert rec["labels"] == e["injected_by_sc"]           # the injected floor rides along
        # It classifies exactly as the real file would when Drive lists it.
        assert inv.classify(rec)["format"] == e["format"]
        assert inv.classify(rec)["status"] == inv.ASSESSABLE


def test_every_labeled_file_is_located_among_the_estate():
    labeled = sa.labeled_records(ENTRIES)
    files, folders, _ = __import__("scale_corpus").generate(n=2000, seed=4)
    estate = sa.embed(files, labeled, seed=1)
    located = sa.ground_truth(estate)
    # None dropped, none duplicated, none swallowed by the 30k — the discovery-at-scale guarantee.
    assert len(located) == len(labeled)
    assert {r["id"] for r in located} == {r["id"] for r in labeled}
    assert len({r["id"] for r in estate}) == len(estate)      # ids unique across the whole estate
    # Labels survive the embedding intact.
    by_name = {r["name"]: r for r in located}
    for e in ENTRIES:
        assert by_name[e["filename"]]["labels"] == e["injected_by_sc"]


def test_embedding_raises_the_estate_assessable_count_by_the_labeled_files():
    labeled = sa.labeled_records(ENTRIES)
    files, folders, _ = __import__("scale_corpus").generate(n=1500, seed=9)
    base = inv.summarize(files + folders)["assessment_eligible"]
    estate = sa.embed(files, labeled, seed=2)
    after = inv.summarize(estate + folders)["assessment_eligible"]
    assert after == base + len(labeled)                       # every labeled file counts as eligible


def test_embed_is_deterministic_for_a_seed():
    labeled = sa.labeled_records(ENTRIES)
    files, _, _ = __import__("scale_corpus").generate(n=500, seed=1)
    a = [r["id"] for r in sa.embed(files, labeled, seed=3)]
    b = [r["id"] for r in sa.embed(files, labeled, seed=3)]
    assert a == b
