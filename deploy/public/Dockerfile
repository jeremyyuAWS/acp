# acp public-demo image: FastAPI control plane serving the React SPA same-origin,
# with both analysis engines bundled as COMPILED artifacts (no diligence source):
#   - .NET 10 Office CLI  (spike/dotnet/.../Release: AcpScan.Cli + DigitalA11y.*.dll)
#   - Python PDF analyser (worker-python: analysers/ + models/, vendored by deploy.sh)
# Build context is the acp/ repo root.  Base images via mirror.gcr.io to dodge
# the docker.io 429s the Temporal standup hit.

# ---- stage 1: build the SPA (same-origin → relative API base) ----
FROM mirror.gcr.io/library/node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
# npm install instead of npm ci: avoids lockfile/npm-version mismatch between
# local macOS npm and the container's npm when optional peer deps (esbuild) resolve
# to different minor versions across npm releases.
RUN npm install --prefer-offline 2>/dev/null || npm install
COPY frontend/ ./
RUN echo "VITE_API=" > .env.production && npm run build   # -> /web/dist

# ---- stage 2: runtime ----
FROM mirror.gcr.io/library/python:3.12-slim AS runtime
WORKDIR /app

# .NET 10 runtime (for the Office analyser CLI); libicu is required by the CLR
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates libicu-dev \
    && curl -fsSL https://dot.net/v1/dotnet-install.sh -o /tmp/dotnet-install.sh \
    && bash /tmp/dotnet-install.sh --runtime dotnet --channel 10.0 --install-dir /usr/share/dotnet \
    && ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet \
    && rm /tmp/dotnet-install.sh \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# python deps — the PDF engine only needs pikepdf+pdfplumber+pydantic, all already
# in api/requirements.txt, so the engine's own (playwright-heavy) reqs are skipped.
COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# app code + config + bundled sample corpus
COPY api/ /app/api/
COPY scripts/ /app/scripts/
COPY config/ /app/config/
COPY test-corpus/files/ /app/test-corpus/files/

# compiled engines (no source)
COPY spike/dotnet/AcpScan.Cli/bin/Release/net10.0/ /app/engine/office/
COPY deploy/public/vendor/worker-python/ /app/engine/worker-python/

# built SPA
COPY --from=web /web/dist/ /app/static/

ENV ACP_DOTNET=/usr/local/bin/dotnet \
    ACP_OFFICE_CLI=/app/engine/office/AcpScan.Cli.dll \
    ACP_PDF_ENGINE=/app/engine/worker-python \
    ACP_STATIC_DIR=/app/static \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    PORT=8077
EXPOSE 8077
WORKDIR /app/api
# Materialize the Drive ADC secret (if provided) to a file google-auth can read,
# then start the server.
CMD ["sh", "-c", "if [ -n \"$ACP_GOOGLE_ADC\" ]; then printf '%s' \"$ACP_GOOGLE_ADC\" > /tmp/adc.json && export GOOGLE_APPLICATION_CREDENTIALS=/tmp/adc.json; fi; exec python -m uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
