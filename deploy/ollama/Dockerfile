# Ollama with two models baked into the image, so both are present at startup with
# no multi-GB cold-start download:
#   * llama3.1:8b  — text: explanations / fix suggestions / compliance digest (~4.7GB)
#   * moondream    — vision: genuine image alt text for WCAG 1.1.1 remediation (~1.7GB)
# CPU inference. Both are LOCAL Ollama models — no third-party AI SDK/key, so the
# "no third-party AI" claim holds for vision too. Wire the app via OLLAMA_BASE_URL,
# OLLAMA_MODEL=llama3.1:8b, and OLLAMA_VISION_MODEL=moondream.
#
# Memory: the vision model was llava:7b (~4.5GB). llama + llava = ~9.2GB did NOT fit the
# Consumption profile's 8Gi ceiling, so OLLAMA_MAX_LOADED_MODELS=1 forced an unload/reload
# between text and vision calls — and the reload window, widened by concurrent workers,
# pushed the container past 8Gi and OOM-killed it (instant request failures, seen in the
# vision traces). moondream is ~1.7GB, so llama + moondream = ~6.4GB and BOTH stay resident:
# OLLAMA_MAX_LOADED_MODELS=2, no swap, no reload cost, no OOM window. It is also a smaller
# model, so a CPU inference returns faster than llava's ~60s. The trade is caption detail —
# moondream is a compact captioner, not a 7B VLM; revisit if alt-text quality regresses.
FROM ollama/ollama:latest

ENV OLLAMA_MAX_LOADED_MODELS=2
# Bake + serve models from a NON-volume path. The base image declares `VOLUME /root/.ollama`,
# so under a runtime that mounts an empty volume there (Azure Container Apps / K8s emptyDir) the
# models baked into the image layer are SHADOWED — the container starts with an empty model list
# and vision silently falls back / templates. Baking to /models (not a declared volume) keeps them
# visible at runtime. Without this the image "ships" the models but the container never sees them.
ENV OLLAMA_MODELS=/models

# Start the server, pull both models into /models (persisted in the layer, not shadowed at
# runtime), verify, then stop. `set -e` + no error-swallowing `|| true` means a failed pull FAILS
# the build instead of shipping an empty image (the defect this used to have). `ollama list` prints
# the baked inventory into the build log.
RUN set -e; \
    ollama serve & SP=$!; \
    for i in $(seq 1 60); do curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done; \
    ollama pull llama3.1:8b; \
    ollama pull moondream; \
    ollama list; \
    test -d /models/manifests; \
    kill $SP 2>/dev/null || true

ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
