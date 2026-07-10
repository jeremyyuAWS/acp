"""The human-task view is a contract: every criterion the platform knows has a human home.

The point of human_categories is that a reviewer never has to understand WCAG. That promise
breaks the moment a criterion exists in the catalog with no category — it would surface in the
inbox as a bare "1.3.5" with no plain name, which is exactly the failure this module exists to
prevent. So the binding test is total coverage of RULE_CATALOG, enforced here rather than
discovered by a customer.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import human_categories as hc  # noqa: E402
import store  # noqa: E402


def test_every_catalog_criterion_has_a_human_home():
    """A criterion with no mapping would render as a naked WCAG id in the inbox — the very
    thing this module removes. Adding a criterion to RULE_CATALOG must force a mapping here."""
    missing = [r["id"] for r in store.RULE_CATALOG if hc.category_of(r["id"]) is None]
    assert not missing, (
        "these criteria have no human category — a reviewer would see a bare WCAG id:\n  "
        + ", ".join(missing))


def test_every_mapping_points_at_a_defined_category():
    """A typo'd category key would drop the criterion out of every grouped view silently."""
    for sc in {r["id"] for r in store.RULE_CATALOG}:
        key = hc.category_of(sc)
        if key is not None:
            assert key in hc.CATEGORIES, f"{sc} maps to undefined category {key!r}"


def test_human_name_is_never_the_wcag_title():
    """The whole value is that the name is act-on-it plain language, not the standard's wording.
    A human name that merely echoes the WCAG title (or the id) is the mapping doing nothing."""
    titles = {r["id"]: r["name"] for r in store.RULE_CATALOG}
    for r in store.RULE_CATALOG:
        name = hc.human_name(r["id"])
        assert name, f"{r['id']} has no human name"
        assert name != titles[r["id"]], f"{r['id']} human name just echoes the WCAG title"
        assert r["id"] not in name, f"{r['id']} human name leaks the WCAG id"


def test_describe_keeps_the_wcag_id_as_metadata():
    """WCAG is demoted, not deleted: the auditor still needs the id. describe() must carry it."""
    d = hc.describe("1.1.1")
    assert d["wcag"] == "1.1.1"
    assert d["category"] == "images"
    assert d["human_name"] == "Missing image description"
    assert d["icon"] and d["category_label"] == "Images"
    assert hc.describe("9.9.9") is None            # unknown criterion → no fabricated home


def test_group_by_category_is_ordered_and_drops_nothing_mapped():
    """The grouped view a report/inbox renders: presentation order by category, criteria sorted,
    and — critically — no mapped criterion silently dropped."""
    scs = ["1.1.1", "1.3.1", "2.4.2", "3.1.1", "2.4.4", "1.4.3"]
    groups = hc.group_by_category(scs)
    # ordered by the category order, images (1) before contrast (7) before doc_props (8)
    keys = [g["category"] for g in groups]
    assert keys == sorted(keys, key=lambda k: hc.CATEGORIES[k]["order"])
    assert keys[0] == "images"
    # every input criterion lands in exactly one group
    landed = [c["wcag"] for g in groups for c in g["criteria"]]
    assert sorted(landed) == sorted(scs)
    # an image group carries the human name, not the WCAG title
    images = next(g for g in groups if g["category"] == "images")
    assert images["criteria"][0]["human_name"] == "Missing image description"


def test_unmapped_criteria_are_dropped_not_mishomed():
    """A criterion with no mapping must not be forced under a wrong heading — better absent than
    mislabelled. (Coverage above guarantees no catalog criterion is actually unmapped.)"""
    groups = hc.group_by_category(["1.1.1", "9.9.9"])
    landed = [c["wcag"] for g in groups for c in g["criteria"]]
    assert landed == ["1.1.1"]
