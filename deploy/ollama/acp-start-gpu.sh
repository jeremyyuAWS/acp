#!/bin/sh
# Runs both processes the GPU image needs: Ollama itself (bound to 127.0.0.1 only — see
# Dockerfile.gpu's OLLAMA_HOST) and acp-ollama-gate.py, the only thing actually listening on the
# externally-exposed port. See acp-ollama-gate.py's own docstring for why this gate exists.
set -e
ollama serve &
exec python3 /usr/local/bin/acp-ollama-gate.py
