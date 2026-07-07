# Ollama with llama3.1 (8B) baked into the image, so the model is present at
# startup with no multi-GB cold-start download. CPU inference — slower than the
# 3B it replaces, chosen for better explanation/digest prose. Needs ~5GB model +
# runtime; the acp-ollama container is 8Gi. Wire the app via OLLAMA_BASE_URL and
# OLLAMA_MODEL=llama3.1:8b.
FROM ollama/ollama:latest

# Start the server, pull the model into /root/.ollama (persisted in the layer),
# then stop the server. The model ships inside the image.
RUN bash -c 'ollama serve & SP=$!; \
    for i in $(seq 1 30); do curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done; \
    ollama pull llama3.1:8b; \
    kill $SP 2>/dev/null; wait $SP 2>/dev/null || true'

ENV OLLAMA_HOST=0.0.0.0:11434
EXPOSE 11434
