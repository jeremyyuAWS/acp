"""The operator's configuration page and the seam guard are one fact written twice.

`packaging/docs/application-configuration.md` tells an operator which names the chart sets and
which it does not. `tests/test_packaging_seams.py` holds the same list as a guard that fails when a
gap closes. A page that drifts from the guard is worse than no page: it is the one an operator
reads when a variable is unset, and its wrong answer is "there is no way to set this".

So the page is derived-checked rather than proof-read. The names must match exactly in both
directions, and the recipe each row gives must be one the chart really honours — which is asserted
by rendering it, not by reading the template.
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest
import yaml

from packaging_helpers import PACKAGING, load_example
from test_packaging_seams import NOT_WIRED_BY_THE_CHART

PAGE = PACKAGING / "docs" / "application-configuration.md"
CHART = PACKAGING / "chart" / "acp"
HELM = shutil.which("helm")

needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed")


def _rows() -> dict[str, str]:
    """The gap table, as {variable: how-to-set-it}."""
    rows = {}
    for line in PAGE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| `([A-Z0-9_]+)` \| (.+?) \| (.+?) \|$", line)
        if match:
            rows[match.group(1)] = match.group(3)
    return rows


def test_the_page_lists_exactly_the_gaps_the_guard_holds():
    """Both directions. A gap closed without deleting its row leaves an operator following a
    recipe for something already wired; a gap opened without adding one leaves them with a
    variable the page implies is set."""
    assert set(_rows()) == set(NOT_WIRED_BY_THE_CHART), (
        f"page: {sorted(_rows())}\nguard: {sorted(NOT_WIRED_BY_THE_CHART)}")


def test_every_row_says_what_the_absence_costs_and_what_to_do():
    for name, recipe in _rows().items():
        assert recipe.strip(), name
        assert "secrets.refs." in recipe or "no path" in recipe, (
            f"{name}: a row that names no recipe is a row an operator cannot act on")


@needs_helm
def test_the_recipes_the_page_gives_actually_produce_the_variable():
    """THE HALF THAT WOULD OTHERWISE BE PROSE. Each row that names a `secrets.refs` key is a claim
    that declaring it sets that variable — and the claim rests on the projection's exact spelling
    rule (uppercase, hyphens to underscores). One character wrong in this page and an operator
    creates a Secret, declares a reference, sees a variable appear in the pod, and still has the
    one they needed unset.

    So the recipes are rendered rather than read. All of them at once, because the failure being
    guarded against is a name that is nearly right.
    """
    from acpctl.values import render_values_yaml

    doc = load_example("standard-production")
    expected = {}
    for name, recipe in _rows().items():
        key = re.search(r"secrets\.refs\.([a-z0-9-]+)", recipe)
        if not key:
            continue
        doc["secrets"]["refs"][key.group(1)] = {"name": "kv-acp", "key": key.group(1)}
        expected[name] = key.group(1)
    assert expected, "no recipe was testable; this test would prove nothing"

    proc = subprocess.run([HELM, "template", "acp", str(CHART), "-f", "-"],
                          input=render_values_yaml(doc), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    rendered = set()
    for manifest in yaml.safe_load_all(proc.stdout):
        if manifest and manifest["kind"] == "Deployment":
            for container in manifest["spec"]["template"]["spec"]["containers"]:
                rendered.update(e["name"] for e in container.get("env", []))
    missing = {n: k for n, k in expected.items() if n not in rendered}
    assert not missing, f"the page's recipe does not produce these: {missing}"


@needs_helm
def test_the_computed_names_the_page_claims_are_computed_really_are():
    """The other half of the page: the list an operator must NOT try to set, because the chart
    owns it. A name that has since become configurable, or one that was never rendered at all,
    makes that paragraph advice about the wrong variables."""
    from acpctl.values import render_values_yaml

    text = PAGE.read_text(encoding="utf-8")
    claimed = set(re.findall(r"`([A-Z][A-Z0-9_]{3,})`", text.split("**2. A document field")[0]))

    # RENDERED WITH EVERY CONDITION MET, because several of these are conditional and a render
    # that omits one cannot tell "the chart never sets this" from "this installation did not ask
    # for it". The page says as much; this is the same fact asserted. `connectionPool` is the one
    # no shipped example sets, and it was what caught the page claiming an unconditional group.
    doc = load_example("standard-production")
    doc["ai"]["mode"] = "local-only"
    doc["ai"]["ollama"]["enabled"] = True
    doc["observability"]["openTelemetry"] = {"enabled": True, "exporter": "azure-monitor"}
    doc["api"]["connectionPool"] = 40
    proc = subprocess.run([HELM, "template", "acp", str(CHART), "-f", "-"],
                          input=render_values_yaml(doc),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    rendered = set()
    for manifest in yaml.safe_load_all(proc.stdout):
        if manifest and manifest["kind"] in ("Deployment", "Job"):
            for container in manifest["spec"]["template"]["spec"]["containers"]:
                rendered.update(e["name"] for e in container.get("env", []))
    assert claimed, "the page names no computed variables; this test would prove nothing"
    assert claimed <= rendered, f"claimed as computed but not rendered: {sorted(claimed - rendered)}"
