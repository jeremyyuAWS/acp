# Ollama with two models baked into the image, so both are present at startup with
# no multi-GB cold-start download:
#   * llama3.1:8b  — text: explanations / fix suggestions / compliance digest (~4.7GB)
#   * llava:7b     — vision: genuine image alt text for WCAG 1.1.1 remediation (~4.7GB)
# CPU inference. Both are LOCAL Ollama models — no third-party AI SDK/key, so the
# "no third-party AI" claim holds for vision too. Wire the app via OLLAMA_BASE_URL,
# OLLAMA_MODEL=llama3.1:8b, and OLLAMA_VISION_MODEL=llava:7b.
#
# Memory: each model is ~5GB. The acp-ollama container runs on the Consumption profile
# (8Gi ceiling), which can't hold BOTH models resident. OLLAMA_MAX_LOADED_MODELS=1 makes
# Ollama unload the text model before loading llava (and vice-versa) instead of trying to
# keep both — so a vision remediation never OOMs the container; the cost is a ~15s cold
# reload of the text model on the next explain/suggest call. The app does NOT prewarm
# llava, so it only loads while a remediation job runs.
FROM ollama/ollama:latest

ENV OLLAMA_MAX_LOADED_MODELS=1

# Start the server, pull both models into /root/.ollama (persisted in the layer),
# then stop the server. The models ship inside the image.
RUN bash -c 'ollama serve & SP=$!; \
    for i in $(seq 1 30); do curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done; \
    ollama pull llama3.1:8b; \
    ollama pull llava:7b; \
    kill $SP 2>/dev/null; wait $SP 2>/dev/null || true'

ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
