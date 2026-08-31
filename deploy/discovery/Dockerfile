# Pin to the tested production engine; update Discovery independently of web releases.
ARG BASE_IMAGE=mdkaccessibilityacr.azurecr.io/acp-app:42d6cd9-1788204882
FROM ${BASE_IMAGE}
COPY api/core.py /app/api/core.py
ENV ACP_WORKER_ROLE=discovery ACP_WORKERS=3 ACP_DEFER_ANALYSIS_TO_ASSESS=1 ACP_INLINE_DISCOVER=0
CMD ["acp-worker"]
