"""The model-comparison harness, and the local Ollama service it talks to.

Source-level: the harness's value is in what it REFUSES to do, and refusals are visible in the
code and invisible in a run. A test that executed it would need a running Ollama and several
gigabytes of models — which is the opposite of a check that runs on every push.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = (ROOT / "scripts" / "bench_models.py").read_text()
COMPOSE = (ROOT / "deploy" / "compose" / "docker-compose.yml").read_text()


def test_the_harness_drafts_through_ai_py_not_a_bespoke_prompt():
    """A hand-rolled prompt would benchmark a prompt this product does not use, while reading as
    evidence about ACP. Going through ai.suggest_fix / ai.describe_image is what makes the result
    a statement about the shipped lane."""
    assert "ai.suggest_fix(" in BENCH
    assert "ai.describe_image(" in BENCH
    assert not re.search(r'"/api/generate"', BENCH), "the harness calls Ollama directly somewhere"


def test_it_selects_the_model_the_way_ai_py_does():
    """Via the env var ai.py already reads, then a reload — not by patching module internals,
    which would test a path no deployment uses."""
    assert 'os.environ["OLLAMA_MODEL"] = model' in BENCH
    assert 'os.environ["OLLAMA_VISION_MODEL"] = model' in BENCH
    assert "importlib.reload(ai)" in BENCH


def test_a_missing_model_is_reported_and_skipped_never_pulled():
    """A benchmark that downloads 20GB because of a typo is not one anybody runs twice."""
    assert re.search(r"skip \{m\} — not pulled", BENCH)
    assert "ollama pull" in BENCH, "the skip message should say how to fix it"
    assert not re.search(r'"/api/pull"', BENCH), "the harness pulls models itself"


def test_it_does_not_score():
    """There is no ground truth for 'good alt text'. A 7.4 nobody can defend gets quoted in a
    deck; the drafts are the deliverable and the judgement stays human — the same posture ai.py
    takes (draft, approve, apply, never auto-write)."""
    assert "No scores, by design" in BENCH
    for word in ("score =", "rating", "grade", "rank("):
        assert word not in BENCH, f"the harness computes a {word!r}"


def test_a_model_that_errors_is_a_result_not_a_crash():
    """One bad model must not end the comparison — the others are the reason it was run."""
    assert BENCH.count("except Exception as e:") >= 2
    assert '"ok": False' in BENCH


def test_unreachable_ollama_says_how_to_start_it():
    assert "docker compose up -d ollama" in BENCH
    assert "OLLAMA_BASE_URL" in BENCH


def test_compose_runs_ollama_on_a_volume_not_a_baked_image():
    """Locally the constraint is the opposite of the cloud's: trying a model must not mean
    rebuilding an image. deploy/ollama/Dockerfile bakes models on purpose for deployment — this
    stack deliberately does not."""
    svc = COMPOSE[COMPOSE.index("\n  ollama:"):]
    svc = svc[:svc.index("\n  grafana:")]
    assert "image: ollama/ollama:latest" in svc, "the compose service builds instead of pulling"
    assert "acp-ollama:/root/.ollama" in svc, "models are not on a persistent volume"
    assert "build:" not in svc


def test_the_app_is_wired_to_the_service_with_a_working_default():
    """`${OLLAMA_BASE_URL:-http://ollama:11434}` — the service name, so a stack brought up with
    no .env still reaches it. api/ai.py degrades to deterministic prose if it cannot, so a stack
    WITHOUT the service still works; this only decides whether drafting happens."""
    assert "OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://ollama:11434}" in COMPOSE
    assert "OLLAMA_MODEL: ${OLLAMA_MODEL:-llama3.1:8b}" in COMPOSE
    assert "OLLAMA_VISION_MODEL: ${OLLAMA_VISION_MODEL:-moondream}" in COMPOSE


def test_the_healthcheck_does_not_require_a_pulled_model():
    """/api/tags answers on an empty volume. A check that needed a model would report unhealthy
    in exactly the state a fresh clone is in."""
    svc = COMPOSE[COMPOSE.index("\n  ollama:"):]
    svc = svc[:svc.index("\n  grafana:")]
    assert "/api/tags" in svc
