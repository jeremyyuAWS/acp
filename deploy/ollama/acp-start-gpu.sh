#!/bin/sh
# Runs both processes the GPU image needs: Ollama itself (bound to 127.0.0.1 only — see
# Dockerfile.gpu's OLLAMA_HOST) and acp-ollama-gate.py, the only thing actually listening on the
# externally-exposed port. See acp-ollama-gate.py's own docstring for why this gate exists.
set -e
# Do not trust the Container App's persisted environment here. An older provisioning runbook
# stamped OLLAMA_HOST=0.0.0.0:11434, which made Ollama take the gate's public port first: either
# the gate failed to bind or requests bypassed it entirely. The entrypoint is the final authority
# for every create, image update and revision restart, so Ollama always remains loopback-only.
export OLLAMA_HOST=127.0.0.1:11500
export ACP_OLLAMA_UPSTREAM=http://127.0.0.1:11500
ollama serve &
exec python3 /usr/local/bin/acp-ollama-gate.py
