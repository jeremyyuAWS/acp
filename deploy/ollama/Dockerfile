# Ollama with llama3.2 (3B) baked into the image, so the model is present at
# startup with no multi-GB cold-start download. CPU inference — slow but works
# for ACP's /ai/explain. Wire the app via OLLAMA_BASE_URL.
FROM ollama/ollama:latest

# Start the server, pull the model into /root/.ollama (persisted in the layer),
# then stop the server. The model ships inside the image.
RUN bash -c 'ollama serve & SP=$!; \
    for i in $(seq 1 30); do curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done; \
    ollama pull llama3.2; \
    kill $SP 2>/dev/null; wait $SP 2>/dev/null || true'

ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
