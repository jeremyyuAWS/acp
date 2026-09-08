"""The release manifest contract: what one ACP release consists of, and what it refuses.

THE DIVERGENCE THIS CONTRACT EXISTS FOR, stated once so the tests below read as a group. Before
it, three parts of this repository disagreed about which images an ACP install runs and nothing
noticed:

  `acpctl plan`   named eight images from inventory.IMAGES, each with `digest <unresolved>`
  `helm template` deployed four — `acp`, `acp-worker`, `acp-ollama-gateway`, `acp-grafana`
  the build      produced none of those eight and only two of those four

Two names overlapped out of eight. A reviewer signing off a plan was reading a list of artifacts
that, for six of its entries, had never been built. The rules under "coverage" below are the ones
that make that state un-representable: a manifest cannot describe a release while an image the
plan names, or one the chart pulls, has no artifact behind it.

EVERY RULE HAS A TEST THAT MAKES IT FIRE. Take a valid manifest, break exactly one thing, assert
the rule id — the same discipline tests/test_packaging_validate.py applies to the deployment
contract, for the same reason: a rule with no failing case is a claim, not a check.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess

import pytest
import yaml

from packaging_helpers import PACKAGING, load_example

MANIFEST = PACKAGING / "examples" / "example.acp-release.yaml"
CHART = PACKAGING / "chart" / "acp"
HELM = shutil.which("helm")

needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed")

REVISION = "0" * 40
OTHER_REVISION = "a" * 40


def load_manifest() -> dict:
    from acpctl.release import load_manifest as load
    return copy.deepcopy(load(MANIFEST))


def rules_for(document: dict) -> list[str]:
    from acpctl.release import validate
    return [f.rule for f in validate(document).errors]


def warnings_for(document: dict) -> list[str]:
    from acpctl.release import validate
    return [f.rule for f in validate(document).warnings]


def run(argv, capsys):
    from acpctl.cli import main
    code = main(argv)
    return code, capsys.readouterr()


def component(document: dict, name: str) -> dict:
    return next(c for c in document["components"] if c["name"] == name)


# ── the schema itself ─────────────────────────────────────────────────────────
def test_schema_uses_no_keyword_the_evaluator_ignores():
    """Same guard as the deployment schema. An unsupported keyword is INVISIBLE otherwise: an
    evaluator that skips a constraint reports the document as valid."""
    from acpctl.jsonschema_mini import ANNOTATIONS, SUPPORTED, keywords_used
    from acpctl.release import load_schema
    unknown = keywords_used(load_schema()) - SUPPORTED - ANNOTATIONS
    assert not unknown, (
        f"acp-release.schema.json uses {sorted(unknown)}, which jsonschema_mini does not "
        f"implement, so those constraints are not enforced")


def test_every_ref_in_the_schema_resolves():
    from acpctl.jsonschema_mini import Validator
    from acpctl.release import load_schema
    schema = load_schema()
    validator = Validator(schema)
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                refs.append(node["$ref"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    assert refs, "the schema has no $refs at all — this test would pass vacuously"
    for ref in refs:
        assert validator._resolve(ref), ref


def test_the_serves_enum_is_exactly_the_images_the_plan_names():
    """PINNED IN BOTH DIRECTIONS, because either drift is silent.

    An image added to inventory.IMAGES but not to the enum can never be served, so every release
    manifest becomes invalid with a rule firing about a name the schema rejects. One removed from
    IMAGES but left in the enum lets a release claim to serve an image nothing installs.
    """
    from acpctl.inventory import IMAGES
    from acpctl.release import load_schema
    enum = load_schema()["$defs"]["component"]["properties"]["serves"]["items"]["enum"]
    assert sorted(enum) == sorted(IMAGES), (
        "the release schema's `serves` enum and inventory.IMAGES have drifted; they are the same "
        "list of PRD S5.1 images and `acpctl plan` reads the second one")


def test_the_chart_image_components_are_the_ones_the_chart_asks_for():
    """`CHART_IMAGE_COMPONENTS` is a COPY of what the chart's templates request, and this test is
    what stops it being a stale copy.

    It reads the templates rather than the values file on purpose: `image.digests` in values.yaml
    is `{}` and says nothing about which keys are looked up. The lookup is in the templates, as
    `include "acp.image" (dict "root" $ "component" "<name>")`, and a component missing from the
    tuple is an image no release pins — which fails SILENTLY, because acp.image falls back to the
    tag and the install succeeds unpinned.
    """
    from acpctl.release import CHART_IMAGE_COMPONENTS
    asked = set()
    for path in sorted((CHART / "templates").glob("*.yaml")):
        asked.update(re.findall(r'"acp\.image"\s+\(dict\s+"root"\s+\$\s+"component"\s+"(\w+)"\)',
                                path.read_text(encoding="utf-8")))
    assert asked, "no acp.image call found in the chart templates — this test would pass vacuously"
    assert asked == set(CHART_IMAGE_COMPONENTS), (
        f"the chart asks acp.image for {sorted(asked)} but release.py pins "
        f"{sorted(CHART_IMAGE_COMPONENTS)}")


# ── the shipped example ───────────────────────────────────────────────────────
def test_the_shipped_example_is_a_valid_release():
    from acpctl.release import validate
    result = validate(load_manifest())
    assert result.ok, [f.render() for f in result.errors]


def test_the_shipped_example_cannot_install_anything():
    """THE SAFETY PROPERTY OF SHIPPING AN EXAMPLE WITH DIGESTS IN IT.

    Fabricated digests in a file people copy are more dangerous than a placeholder hostname: a
    copied deployment document fails validation, a copied release manifest passes and pins bytes
    nobody chose. The registry is in a reserved TLD (RFC 2606) that can never resolve, so the copy
    fails at pull time — and `release verify` says so rather than leaving it to be discovered.
    """
    assert "release.illustrative" in warnings_for(load_manifest())
    host = load_manifest()["metadata"]["registry"].split("/")[0]
    assert host.endswith(".invalid")


def test_the_example_records_the_artifacts_this_repository_actually_builds():
    """The manifest is the place the three disagreeing counts are reconciled, so the example has
    to record the real one: ONE application artifact serving the API, the three worker roles, and
    both hook Jobs, plus the model and dashboard images."""
    doc = load_manifest()
    assert component(doc, "app")["serves"] == [
        "api", "discover", "assess", "remediate", "migrations", "preflight"]
    assert component(doc, "app")["chartImages"] == ["api", "worker"]
    assert {c["repository"] for c in doc["components"]} == {
        "acp-app", "acp-ollama-gateway", "acp-grafana"}


# ── rules: each one made to fire ──────────────────────────────────────────────
def test_a_component_from_another_commit_is_a_mixed_release():
    """PRD S5.1: one source revision per release. A fleet whose API and workers came from
    different commits can pass every smoke test and still be a combination nobody built."""
    doc = load_manifest()
    component(doc, "grafana")["sourceRevision"] = OTHER_REVISION
    assert "release.mixed-revision" in rules_for(doc)


def test_two_components_may_not_share_a_name():
    doc = load_manifest()
    component(doc, "grafana")["name"] = "app"
    assert "release.duplicate-component" in rules_for(doc)


def test_an_unsigned_component_is_refused():
    """PRD S5.1 signs every release image and PRD S13 verifies before deployment. A component
    with no signature cannot be verified later, so it is refused now."""
    doc = load_manifest()
    del component(doc, "app")["signature"]
    assert "release.unsigned" in rules_for(doc)


def test_a_component_without_an_sbom_is_refused():
    doc = load_manifest()
    del component(doc, "app")["sbom"]
    assert "release.no-sbom" in rules_for(doc)


def test_an_image_the_plan_names_must_have_an_artifact_behind_it():
    """THE RULE THE CONTRACT EXISTS FOR. `acpctl plan` prints one line per inventory.IMAGES
    entry; before this, six of the eight were built by nothing and the plan presented them to a
    reviewer as artifacts."""
    doc = load_manifest()
    component(doc, "app")["serves"].remove("preflight")
    rules = rules_for(doc)
    assert "release.image-unserved" in rules


def test_two_artifacts_may_not_both_claim_one_logical_image():
    doc = load_manifest()
    component(doc, "grafana")["serves"].append("preflight")
    assert "release.image-ambiguous" in rules_for(doc)


def test_an_image_the_chart_pulls_must_be_pinned():
    """The silent one. `acp.image` falls back to the tag when image.digests has no entry, so an
    unbacked chart component installs successfully and is simply not pinned — indistinguishable,
    in the rendered manifest, from a release that never claimed to pin anything."""
    doc = load_manifest()
    component(doc, "app")["chartImages"] = ["api"]
    assert "release.chart-image-unpinned" in rules_for(doc)


def test_two_artifacts_may_not_back_one_chart_image():
    doc = load_manifest()
    component(doc, "grafana")["chartImages"].append("worker")
    assert "release.chart-image-ambiguous" in rules_for(doc)


def test_amd64_is_required_on_every_component():
    doc = load_manifest()
    component(doc, "app")["architectures"] = ["arm64"]
    assert "release.no-amd64" in rules_for(doc)


def test_a_release_built_for_arm64_in_part_is_not_an_arm64_release():
    """A WARNING, not an error: PRD S5.1 supports arm64 'where all analysis engines permit it',
    which is a per-image fact. What this stops is the release being SUMMARISED as arm64 in a
    support matrix when one artifact is amd64-only."""
    doc = load_manifest()
    component(doc, "grafana")["architectures"] = ["amd64", "arm64"]
    result_warnings = warnings_for(doc)
    assert "release.partial-arm64" in result_warnings
    assert rules_for(doc) == [], "a partial arm64 build is legal; it must not fail"


def test_a_uniformly_arm64_release_raises_no_partial_warning():
    """The other direction, so the warning above cannot pass vacuously."""
    doc = load_manifest()
    for c in doc["components"]:
        c["architectures"] = ["amd64", "arm64"]
    assert "release.partial-arm64" not in warnings_for(doc)


def test_a_structurally_broken_manifest_stops_before_the_semantic_rules():
    """Same reason as the deployment contract: semantic rules index into the document freely, and
    running them over a structurally invalid one produces KeyErrors dressed as findings."""
    doc = load_manifest()
    doc["components"][0]["digest"] = "not-a-digest"
    assert rules_for(doc) == ["schema"]


# ── using a release with a deployment document ────────────────────────────────
def test_a_release_that_is_not_the_one_the_document_asks_for_is_refused():
    from acpctl.release import check_against_document, validate
    release = validate(load_manifest()).release
    doc = load_example("standard-production")
    doc["runtime"]["version"] = "2027.1"
    findings = check_against_document(release, doc)
    assert [f.rule for f in findings] == ["release.version-mismatch"]


def test_the_matching_release_raises_nothing():
    from acpctl.release import check_against_document, validate
    release = validate(load_manifest()).release
    assert check_against_document(release, load_example("standard-production")) == []


# ── values ────────────────────────────────────────────────────────────────────
def test_values_without_a_release_are_unchanged():
    """The unpinned path must stay byte-identical: an empty digest map is an honest 'not
    resolved', and emitting the chart's own repository defaults here would be a second place for
    them to live."""
    from acpctl.values import build_values
    image = build_values(load_example("standard-production"))["image"]
    assert image["digests"] == {}
    assert "repository" not in image and "workerRepository" not in image


def test_values_with_a_release_pin_every_chart_image():
    from acpctl.release import CHART_IMAGE_COMPONENTS, validate
    from acpctl.values import build_values
    release = validate(load_manifest()).release
    image = build_values(load_example("standard-production"), release)["image"]
    assert set(image["digests"]) == set(CHART_IMAGE_COMPONENTS)
    assert all(d.startswith("sha256:") for d in image["digests"].values())
    assert image["repository"] == "acp-app"
    assert image["workerRepository"] == "acp-app"


def test_the_pull_registry_comes_from_the_document_not_the_release():
    """A digest names the same bytes in any registry. An installation that mirrored the release
    into its own registry (PRD S17, air-gapped) pulls from ITS host with these digests unchanged,
    so taking the registry from the manifest would send every mirrored install back to the
    build's registry."""
    from acpctl.release import validate
    from acpctl.values import build_values
    release = validate(load_manifest()).release
    doc = load_example("standard-production")
    image = build_values(doc, release)["image"]
    assert image["registry"] == doc["runtime"]["imageRegistry"]
    assert image["registry"] != release.registry


def test_the_values_header_says_whether_it_is_pinned():
    from acpctl.release import validate
    from acpctl.values import render_values_yaml
    doc = load_example("standard-production")
    assert "UNRESOLVED" in render_values_yaml(doc)
    pinned = render_values_yaml(doc, validate(load_manifest()).release)
    assert "UNRESOLVED" not in pinned
    assert "Pinned to release 2026.9" in pinned
    assert "Signatures are NOT verified" in pinned


# ── plan ──────────────────────────────────────────────────────────────────────
def test_the_plan_pins_every_image_it_names():
    """The anti-divergence assertion, in the direction a reviewer reads. Every image the plan
    lists gets a real digest, and the word `<unresolved>` is gone — which is only true because
    `release.image-unserved` makes a gap impossible."""
    from acpctl.inventory import IMAGES
    from acpctl.plan import render
    from acpctl.release import validate
    text = render(load_example("standard-production"),
                  release=validate(load_manifest()).release)
    assert "<unresolved>" not in text
    for image in IMAGES.values():
        assert f"  {image}:" in text, f"{image} is missing from the plan"
    assert text.count("sha256:") >= len(IMAGES)


def test_the_plan_names_the_artifact_behind_each_image():
    """Six of the eight lines share one digest because they are one artifact. Printing the
    artifact is what stops a reviewer counting six signed images where there are three."""
    from acpctl.plan import render
    from acpctl.release import validate
    text = render(load_example("standard-production"),
                  release=validate(load_manifest()).release)
    assert "(artifact acp-app, amd64)" in text
    assert "(artifact acp-grafana, amd64)" in text


def test_the_plan_without_a_release_still_refuses_to_present_a_tag_as_a_pin():
    from acpctl.plan import render
    assert "digest  <unresolved>" in render(load_example("standard-production"))


# ── the CLI ───────────────────────────────────────────────────────────────────
def test_release_verify_accepts_the_shipped_example(capsys):
    code, out = run(["release", "verify", str(MANIFEST)], capsys)
    assert code == 0, out.err
    assert "3 artifact(s)" in out.out
    assert "not verified" in out.out, "the command must not imply it checked a signature"


def test_release_verify_rejects_a_mixed_revision_release(tmp_path, capsys):
    """The acceptance criterion in the implementation PRD's workstream A, exercised through the
    command CI would run rather than through the rule function."""
    doc = load_manifest()
    component(doc, "grafana")["sourceRevision"] = OTHER_REVISION
    path = tmp_path / "mixed.acp-release.yaml"
    path.write_text(yaml.safe_dump(doc))
    code, out = run(["release", "verify", str(path)], capsys)
    assert code == 1
    assert "release.mixed-revision" in out.err


def test_release_verify_rejects_an_unsigned_release(tmp_path, capsys):
    doc = load_manifest()
    del component(doc, "app")["signature"]
    path = tmp_path / "unsigned.acp-release.yaml"
    path.write_text(yaml.safe_dump(doc))
    code, out = run(["release", "verify", str(path)], capsys)
    assert code == 1
    assert "release.unsigned" in out.err


def test_release_verify_json_is_machine_readable(capsys):
    code, out = run(["release", "verify", str(MANIFEST), "--json"], capsys)
    assert code == 0
    data = json.loads(out.out)
    assert data["version"] == "2026.9"
    assert set(data["chartDigests"]) == {"api", "worker", "ollama", "grafana"}


@pytest.mark.parametrize("command", ["values", "plan"])
def test_an_invalid_release_refuses_rather_than_falling_back_to_unpinned(
        command, tmp_path, capsys):
    """THE FAILURE MODE WORTH A TEST OF ITS OWN. A caller who passed --release asked to pin. If a
    broken manifest degraded to the unpinned path, the output would be a values file or a plan
    that reads exactly like every other one — and nothing would say the pin did not happen."""
    doc = load_manifest()
    component(doc, "app")["sourceRevision"] = OTHER_REVISION
    path = tmp_path / "mixed.acp-release.yaml"
    path.write_text(yaml.safe_dump(doc))
    spec = PACKAGING / "examples" / "standard-production.acp-deployment.yaml"
    code, out = run([command, str(spec), "--release", str(path)], capsys)
    assert code == 1
    assert out.out == ""
    assert "release.mixed-revision" in out.err


def test_a_release_for_another_version_is_refused_by_the_commands(tmp_path, capsys):
    doc = load_manifest()
    doc["metadata"]["version"] = "2027.1"
    path = tmp_path / "future.acp-release.yaml"
    path.write_text(yaml.safe_dump(doc))
    spec = PACKAGING / "examples" / "standard-production.acp-deployment.yaml"
    code, out = run(["values", str(spec), "--release", str(path)], capsys)
    assert code == 1
    assert "release.version-mismatch" in out.err


def test_release_verify_writes_nothing(capsys, monkeypatch):
    """`acpctl release verify` joins the read-only sweep in test_packaging_cli.py rather than
    being exempted from it."""
    import builtins
    real_open = builtins.open

    def guarded(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"release verify opened {file} for writing")
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded)
    assert run(["release", "verify", str(MANIFEST)], capsys)[0] == 0


# ── the render ────────────────────────────────────────────────────────────────
@needs_helm
def test_a_pinned_release_renders_no_image_by_tag():
    """The end of the chain, asserted on the MANIFEST rather than on the values.

    A values test establishes that `image.digests` was populated. It cannot establish that the
    chart used it — `acp.image` could prefer the tag, or a template could build its own image
    string and bypass the helper entirely, and no values assertion would notice. This renders and
    reads every image reference Kubernetes would actually pull.
    """
    from acpctl.release import validate
    from acpctl.values import render_values_yaml
    values = render_values_yaml(load_example("standard-production"),
                                validate(load_manifest()).release)
    proc = subprocess.run([HELM, "template", "acp", str(CHART), "-f", "-"],
                          input=values, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    images = {d["image"]
              for doc in yaml.safe_load_all(proc.stdout) if doc
              for d in _containers(doc)}
    assert images, "nothing rendered a container — this test would pass vacuously"
    for image in images:
        assert "@sha256:" in image, f"{image} is pulled by tag in a pinned release"
    assert any("acp-app@sha256:" in image for image in images), (
        "the application artifact named by the release is not what the chart pulls")


def _containers(manifest: dict) -> list[dict]:
    spec = manifest.get("spec", {})
    pod = spec.get("template", {}).get("spec") or spec.get("jobTemplate", {})
    if not isinstance(pod, dict):
        return []
    return [c for c in pod.get("containers", []) + pod.get("initContainers", [])
            if isinstance(c, dict) and "image" in c]


@needs_helm
def test_an_unpinned_render_still_uses_tags():
    """The companion, so the assertion above cannot pass because of something unrelated."""
    from acpctl.values import render_values_yaml
    proc = subprocess.run([HELM, "template", "acp", str(CHART), "-f", "-"],
                          input=render_values_yaml(load_example("standard-production")),
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    images = {d["image"] for doc in yaml.safe_load_all(proc.stdout) if doc
              for d in _containers(doc)}
    assert images
    assert all("@sha256:" not in image for image in images)
