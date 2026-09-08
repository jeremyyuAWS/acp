"""The GPU image must never let Ollama occupy or bypass its authenticated gate."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OLLAMA = ROOT / "deploy" / "ollama"


def test_gpu_entrypoint_is_the_final_authority_for_the_two_ports():
    """Persisted ACA env survives image updates, so Dockerfile defaults alone are insufficient."""
    script = (OLLAMA / "acp-start-gpu.sh").read_text()
    serve = script.index("ollama serve")
    gate = script.index("acp-ollama-gate.py", serve)

    assert script.index("export OLLAMA_HOST=127.0.0.1:11500") < serve
    assert script.index("export ACP_OLLAMA_UPSTREAM=http://127.0.0.1:11500") < serve
    assert serve < gate
    active = [line.strip() for line in script.splitlines() if not line.lstrip().startswith("#")]
    assert not any("OLLAMA_HOST=0.0.0.0:11434" in line for line in active)


def test_gpu_provisioning_stamps_the_secure_binding_not_the_gate_port():
    runbook = (OLLAMA / "gpu-runbook.sh").read_text()
    assert "OLLAMA_HOST=127.0.0.1:11500" in runbook
    assert "ACP_OLLAMA_UPSTREAM=http://127.0.0.1:11500" in runbook
    assert "OLLAMA_HOST=0.0.0.0:11434" not in runbook


def test_gpu_image_and_gate_agree_on_public_and_private_ports():
    dockerfile = (OLLAMA / "Dockerfile.gpu").read_text()
    gate = (OLLAMA / "acp-ollama-gate.py").read_text()

    assert "ENV OLLAMA_HOST=127.0.0.1:11500" in dockerfile
    assert "ENV ACP_OLLAMA_UPSTREAM=http://127.0.0.1:11500" in dockerfile
    assert '"http://127.0.0.1:11500"' in gate
    assert 'ACP_OLLAMA_GATE_PORT", "11434"' in gate
