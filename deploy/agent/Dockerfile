# A self-hosted Azure Pipelines agent that can run azure-pipelines.yml.
#
# WHY THIS EXISTS. The MovateAI-Foundry org has ONE parallel job, shared across all of
# its pipelines. Observed 2026-08-08: run 500 (PR #182) sat in `notStarted` for the whole
# time run 499 was `inProgress` — every PR queues behind whatever else is building, in an
# org this repo does not control. Azure DevOps grants one SELF-HOSTED parallel job free
# with unlimited minutes, so an agent here is a second lane that nothing else contends for.
#
# It is also a faster lane. A Microsoft-hosted job provisions a clean VM per run and
# re-downloads the .NET SDK, Node and every npm/pip package; this agent keeps _work/ on a
# named volume, so those are warm from the second run onward.
#
# WHAT IT DELIBERATELY DOES NOT DO. No Docker socket is mounted. azure-pipelines.yml
# builds no images — `az acr build` does that server-side in Azure — so the agent has no
# reason to reach the host daemon, and not mounting it means a pipeline change cannot
# quietly acquire root on this machine.

# ── Python 3.12, staged for the agent's tool cache ───────────────────────────────────────
# UsePythonVersion@0 does NOT install anything. That makes it the odd one out in
# azure-pipelines.yml: UseDotNet@2 and UseNode@1 both DOWNLOAD their toolchain when it is
# missing, but UsePythonVersion only SELECTS an interpreter already in the agent's tool
# cache, and fails the job when no version matches. Microsoft-hosted images ship that cache
# pre-baked, which is why the pipeline has never had to think about it — and why a fresh
# self-hosted agent goes red on `Python 3.12`, the very first step, with an error that
# reads like a missing version rather than a missing cache.
#
# Bookworm on both sides on purpose. The interpreter is relocated out of /usr/local, which
# CPython handles (it finds its prefix from the landmark files next to the binary), but it
# still links against the distro's libssl/libffi/zlib. Matching the base distro is what
# keeps that true; pairing this with a different Ubuntu/Debian release is how you get a
# python that dies on `import ssl` at the first pip install.
FROM python:3.12-slim-bookworm AS python-tool

FROM debian:bookworm-slim

# x64/arm64 are the tool cache's names for the arch, and they are NOT docker's names —
# docker says amd64 where the agent says x64. The cache directory is looked up by the
# agent's spelling, so a directory named amd64 is simply never found.
ARG TARGETARCH
ARG PYTHON_VERSION=3.12.12

ENV AGENT_TOOLSDIRECTORY=/azp/_tool \
    DEBIAN_FRONTEND=noninteractive \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl git jq tar \
      # libicu + libssl are .NET's runtime prerequisites. UseDotNet@2 installs the SDK but
      # not these, and without libicu the CLI aborts at startup unless globalization is
      # disabled — which would change how the Office analyser's tests compare strings.
      libicu72 libssl3 \
      # A few api/requirements.txt entries still build from source on arm64 rather than
      # ship a wheel. Kept deliberately: a compiler in the image costs disk once, whereas
      # discovering it is missing costs a red run at the install step.
      build-essential libffi-dev \
      # CPython's own shared-library dependencies. The python:3.12-slim image pulls these in
      # as package dependencies; copying the interpreter out of it copies the binaries and
      # NOT the apt graph, so on a bare bookworm-slim they are simply absent. This is not
      # theoretical tidying — the build below failed on `libsqlite3.so.0: cannot open shared
      # object file` until this line existed. Each of these backs a stdlib module that is
      # optional at BUILD time and mandatory at USE time: pip needs bz2 and lzma to unpack
      # wheels, and the failure is an ImportError several steps into a pipeline run.
      libsqlite3-0 libbz2-1.0 liblzma5 libncursesw6 libreadline8 libuuid1 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# The marker file is not optional and not a convention — the task treats a version
# directory WITHOUT its sibling `.complete` as a half-finished download and ignores it.
# Omit it and the cache looks correct in `ls` while behaving exactly as if it were empty.
RUN set -eux; \
    mkdir -p /azp; \
    case "${TARGETARCH}" in \
      arm64) tool_arch=arm64 ;; \
      amd64) tool_arch=x64 ;; \
      *) echo "unsupported TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    echo "${tool_arch}" > /azp/.tool_arch
COPY --from=python-tool /usr/local /tmp/python-tool
RUN set -eux; \
    tool_arch="$(cat /azp/.tool_arch)"; \
    dest="${AGENT_TOOLSDIRECTORY}/Python/${PYTHON_VERSION}/${tool_arch}"; \
    mkdir -p "$(dirname "${dest}")"; \
    mv /tmp/python-tool "${dest}"; \
    touch "${dest}.complete"; \
    # Prove the relocation survived before the image is ever used. These modules are the ones
    # that go missing when the interpreter is copied out of its own image: each is a separate
    # shared library, none is needed to START python, and every one of them fails at import
    # time — i.e. several steps into a pipeline run, as something that reads like a broken
    # dependency rather than a broken agent. This line is why `libsqlite3-0` is installed
    # above; it caught the omission on the first build.
    "${dest}/bin/python3" -c "import ssl, ctypes, sqlite3, bz2, lzma, zlib, readline; print(ssl.OPENSSL_VERSION)"; \
    # pip is what every `python -m pip install` in the pipeline goes through, and it exercises
    # the compression modules above on real input rather than just importing them.
    "${dest}/bin/python3" -m pip --version

# The agent refuses to run as root unless AGENT_ALLOW_RUNASROOT is set. Rather than set it,
# run as a real user: every pipeline step inherits this identity, and `npm install -g`
# (step: "npm 11") writes into the tool cache, so the user must own it.
RUN useradd --create-home --home-dir /home/agent --shell /bin/bash agent \
    && mkdir -p /azp/_work \
    && chown -R agent:agent /azp /home/agent

COPY --chown=agent:agent start.sh /azp/start.sh
RUN chmod +x /azp/start.sh

USER agent
WORKDIR /azp
ENTRYPOINT ["/azp/start.sh"]
