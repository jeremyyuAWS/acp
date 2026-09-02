# ACP backend TEST toolchain — the environment the "Backend suite" CI job runs in,
# reproduced on a developer machine.
#
# WHY THIS EXISTS. `python -m pytest tests/` on a host without the full toolchain exits 1 with
# dozens of failures across ~8 modules, and none of them are repo breakage: dotnet, pdfplumber,
# langfuse, tesseract and friends are simply absent. That misreading is not hypothetical — on
# 2026-08-19 a session reported "32 pre-existing test failures" and carried the claim through
# four PRs before it turned out to be its own venv. CLAUDE.md's "Verify before you diagnose" is
# about exactly this, and "the tests were already failing" is the claim that ends an
# investigation. An image whose contents are dictated by .github/workflows/ci.yml removes the
# guess.
#
# WHAT IT IS NOT. A DEVELOPER image, not deploy/public/Dockerfile. That one is the runtime: it
# ships COMPILED engines, a built SPA, and no test dependencies. This one ships the .NET *SDK*
# (a runtime cannot build), tests/requirements.txt, and no application code at all — the repo
# arrives as a bind mount, so the suite runs against the working tree rather than against
# whatever was true when the image was built. No secrets, ever; deploy/compose/.env.example is
# the pattern for anything configurable.
#
# WHAT CI INSTALLS, and therefore what is here (ci.yml, job `backend`):
#   python 3.12 · .NET 10 SDK · the Office analyser CLI build · tesseract via
#   scripts/install_tesseract.sh · api/requirements.txt + tests/requirements.txt
#
# And what CI does NOT install, so neither does this: LibreOffice. tests/test_render_page.py
# asserts the no-soffice contract directly — `render.can_render(".pptx") is
# (render._soffice() is not None)` — so adding it would exercise a DIFFERENT branch than the
# gate does. The point of this image is to agree with CI, not to be maximally equipped.
#
# LAYERING. Ordered by how often the inputs change, so a dependency edit does not rebuild the
# world: base (pinned) → apt (~never) → tesseract (a script that changes ~never) → NuGet
# restore (csproj/props only) → pip (requirements files only) → entrypoint. Editing
# api/requirements.txt re-runs pip alone; editing a .cs file, a test, or anything under api/
# re-runs nothing at all, because none of it is in the image.

# ---- base ---------------------------------------------------------------------------------
# The OFFICIAL .NET SDK image on Ubuntu 24.04, chosen over python:3.12-slim + dotnet-install.sh
# (the mechanism deploy/public/Dockerfile.base-api uses) for two reasons that both matter here:
#
#   1. ci.yml runs on `ubuntu-latest`, which is ubuntu-24.04. scripts/install_tesseract.sh
#      reads VERSION_CODENAME to pick its fallback mirror and its whole rung ladder is written
#      against Ubuntu's apt; a Debian base would give a different tesseract build and a rung 3
#      that points at an Ubuntu mirror the image is not configured for. Same distro as the
#      gate, same OCR binary, same answer.
#   2. base-api's own header records that the .NET install is DOWNLOADED at build time and is
#      network-bound — the single slowest thing in that image. A pinned SDK image is bytes from
#      a registry the build already talks to. (base-api needs only the RUNTIME, which is why it
#      can afford the smaller python base; `dotnet build` does not exist in a runtime install,
#      so this image cannot.)
#
# Ubuntu 24.04's default python3 IS 3.12 — the same minor version `actions/setup-python@v5`
# pins in the job — so nothing here has to chase a PPA to match the gate.
FROM mcr.microsoft.com/dotnet/sdk:10.0-noble

ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---- system packages ----------------------------------------------------------------------
# python3 (3.12 on noble) + venv: Ubuntu marks its system python externally-managed (PEP 668),
#   so pip installs into a venv at /opt/venv rather than fighting it with
#   --break-system-packages. The venv is first on PATH, so `python` and `pip` mean the test
#   interpreter everywhere — in the entrypoint, in compose's `command:`, and in a
#   `docker compose exec` shell.
#
#   The `python3` metapackage is NOT redundant with `python3.12`, and leaving it out costs 13
#   tests. tests/test_calver_ordinal.py lifts the ordinal block out of deploy/public/deploy.sh
#   and runs it with `PATH` pinned to "/usr/bin:/bin" — deliberately, so the block is exercised
#   with a hosted runner's PATH and not with whatever the developer has sourced. The block
#   requires an interpreter on that PATH ("python3 required to compute the build date"), and
#   `python3.12` alone installs /usr/bin/python3.12 without the /usr/bin/python3 symlink an
#   ubuntu-latest runner has. Measured: 13 failed → 13 passed on this line alone.
# tzdata: the same block does Pacific-vs-UTC date arithmetic through zoneinfo, which reads the
#   system tz database rather than carrying its own.
# git: five test modules shell out to it (test_progress_log_guard, test_progress_log_generator,
#   test_monitor, test_redeploy_pin_resolution, test_git_credential_helper), and two of the
#   four checks the CI job runs read the repo's commits.
#
# WeasyPrint's native stack (libpango/libpangoft2/libharfbuzz/libfontconfig) and the DejaVu font.
#   These are the one place this image installs something ci.yml does not, and that is not a
#   departure from "what CI installs, and therefore what is here" — it is that rule applied to
#   the ENVIRONMENT rather than to the step list. ci.yml runs on a hosted ubuntu-latest runner,
#   which ships these libraries pre-provisioned; this image is the plain dotnet/sdk:10.0-noble,
#   the same Ubuntu 24.04 without a runner's provisioning, so what the gate gets ambiently has
#   to be asked for here. Agreeing with CI means matching what the suite RUNS AGAINST.
#
#   api/requirements.txt carries weasyprint==69.0 (it renders /scans/{sid}/report.pdf as of
#   #1201), and pip cannot install what it dlopens. Without these, `import weasyprint` raises
#   OSError — NOT ImportError — which `pytest.importorskip` does not catch, so the report suites
#   ERROR at collection here instead of skipping. That is precisely the misreading this image
#   exists to prevent: its own header records a session carrying "32 pre-existing test failures"
#   through four PRs when the cause was an incomplete venv.
#
#   The list is read off weasyprint.text.ffi's own dlopen calls, not from documentation —
#   spike/weasyprint-report/requirements.txt says "Pango, cairo, GDK-PixBuf, HarfBuzz", the
#   pre-53 cairo-era list, naming two libraries WeasyPrint 69 never loads. libglib2.0-0
#   (gobject) is omitted because it arrives as a dependency of libpango.
#
#   fonts-dejavu-core is not decoration: the report's File Inventory prints U+2713 and U+2717
#   directly and Liberation Sans carries neither (measured with fontTools against the font
#   file), so without DejaVu they render as .notdef boxes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-venv python3-dev \
       git ca-certificates tzdata \
       libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libfontconfig1 \
       fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && python3 --version
ENV PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/venv

# ---- tesseract (OCR) ----------------------------------------------------------------------
# Through scripts/install_tesseract.sh rather than a bare `apt-get install`, because that
# script IS the repo's install logic: ci.yml and azure-pipelines.yml both call it, every rung
# of its ladder is driven against a stub apt-get by tests/test_install_tesseract.py, and a
# fourth hand-rolled copy here would be free to drift from the other three.
#
# ACP_SUDO= is empty-but-SET on purpose. The script reads `SUDO=${ACP_SUDO-sudo}`, so only an
# explicitly-set empty value suppresses sudo — which this image does not have, and does not
# need as root.
#
# NOT optional and NOT softened. ocr.is_available() gates 1.4.5 and 1.4.9; without tesseract
# every test driving them self-skips and the suite still prints green over two missing
# criteria. ci.yml fails the job for precisely that (`Fail if OCR coverage was lost`), so a
# failure here fails the build: no `|| true`, and `tesseract --version` proves the binary is
# real rather than trusting the script's exit code.
COPY scripts/install_tesseract.sh /tmp/install_tesseract.sh
RUN ACP_SUDO= bash /tmp/install_tesseract.sh \
    && rm -f /tmp/install_tesseract.sh \
    && rm -rf /var/lib/apt/lists/* \
    && tesseract --version

# ---- veraPDF (PDF/UA-1 conformance gate) ---------------------------------------------------
# Through scripts/install_verapdf.sh for the same reason tesseract is: ci.yml and
# azure-pipelines.yml both call it, so a fourth hand-rolled copy here would be free to drift.
#
# The JRE is the cost of admission and the reason this is its own layer: veraPDF is a Java
# application, the script exits 1 with "no java on PATH" without one, and the SDK base ships
# .NET rather than Java. `default-jre-headless` keeps it to the runtime — no AWT, no desktop.
#
# WHY IT IS HERE AT ALL, given this image's rule that it installs what CI installs and no more:
# ci.yml installs veraPDF (#1199), so this IS that rule rather than an exception to it. Without
# it the conformance tests in tests/test_report_weasy_structure.py and tests/test_report_pdfua_
# gap.py degrade to a stated skip — milder than the collection error a missing Pango causes, and
# still the thing this image exists to stop a developer misreading: a green suite in which the
# PDF/UA claim was never evaluated.
#
# SOFTENED WHERE TESSERACT IS NOT, and this is the one place this image departs from the gate's
# severity. ci.yml fails the job when veraPDF will not install, because a gate that skips its
# only conformance check is worse than a red one. This is a developer image, often built behind
# a proxy, and a failed fetch from software.verapdf.org should not make the whole toolchain
# unbuildable — so the build continues and the tests say in their own skip reason that the check
# did not run. `|| echo` is the difference between "this image lacks a tool" and "this image
# cannot be built today".
COPY scripts/install_verapdf.sh /tmp/install_verapdf.sh
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jre-headless curl \
    && (bash /tmp/install_verapdf.sh \
        || echo "install_verapdf: FAILED — the conformance tests will skip in this image") \
    && rm -f /tmp/install_verapdf.sh \
    && rm -rf /var/lib/apt/lists/*

# ---- NuGet packages -----------------------------------------------------------------------
# Only the project and props files, so this layer is a function of the DEPENDENCY graph and not
# of the C# sources. `dotnet restore` populates /root/.nuget/packages, which is what lets the
# entrypoint compile the mounted tree in seconds instead of pulling packages on first run.
#
# The relative layout has to survive into the image exactly as it is in the repo: AcpScan.Cli
# reaches its ProjectReferences as ../../../engine/office-analysers/…, and Directory.Build.props
# / Directory.Packages.props apply by directory position, not by name.
WORKDIR /restore
COPY spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj                       spike/dotnet/AcpScan.Cli/
COPY engine/office-analysers/Directory.Build.props                     engine/office-analysers/
COPY engine/office-analysers/Directory.Packages.props                  engine/office-analysers/
COPY engine/office-analysers/DigitalA11y.Core/DigitalA11y.Core.csproj  engine/office-analysers/DigitalA11y.Core/
COPY engine/office-analysers/DigitalA11y.Analysers.DotNet/DigitalA11y.Analysers.DotNet.csproj \
                                                                       engine/office-analysers/DigitalA11y.Analysers.DotNet/
RUN dotnet restore spike/dotnet/AcpScan.Cli/AcpScan.Cli.csproj --nologo

# ---- python dependencies ------------------------------------------------------------------
# Both files, exactly as the job's `Install API + test dependencies` step does.
# tests/requirements.txt is not optional garnish: it carries python-docx/pptx/openpyxl, which
# ~12 modules use to BUILD fixtures — without them the suite aborts during COLLECTION, which is
# the failure that reads as "the repo is broken" rather than as "a dependency is missing".
COPY api/requirements.txt   /tmp/reqs/api/requirements.txt
COPY tests/requirements.txt /tmp/reqs/tests/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
       -r /tmp/reqs/api/requirements.txt \
       -r /tmp/reqs/tests/requirements.txt \
    && rm -rf /tmp/reqs

# ---- runtime ------------------------------------------------------------------------------
# No application code is copied. /app is a BIND MOUNT of the repo (see the `test` service in
# deploy/compose/docker-compose.yml), so what runs is the working tree — uncommitted edits
# included, which is the entire point of a local gate.
WORKDIR /app
COPY deploy/test/entrypoint.sh /usr/local/bin/acp-test-entrypoint
# `acp-checks` runs all FOUR checks the CI job runs. It exists as a command rather than as a
# README one-liner because the README one-liner is how three of them get forgotten: CLAUDE.md
# records a change verified with a green suite that then failed the trailer guard, after the
# commit message was already published and unfixable.
COPY deploy/test/checks.sh /usr/local/bin/acp-checks
RUN chmod +x /usr/local/bin/acp-test-entrypoint /usr/local/bin/acp-checks

# ACP_DOTNET — where the .NET host actually is, and the difference between 8 tests running and
# 8 tests skipping.
#
# tests/engines.py asks `shutil.which("dotnet") is not None or _DOTNET.exists()`, so PATH alone
# satisfies it. FOUR modules do NOT go through engines.py and gate on the path alone:
# test_remediate_structure, test_docx_theme_contrast_engine, test_heading_structure_outline_level
# and test_office_language_rules each build `_DOTNET = Path(os.environ.get("ACP_DOTNET") or
# os.path.expanduser("~/.dotnet/dotnet"))` and skip on `not _DOTNET.exists()`. That default is
# where `actions/setup-dotnet@v4` puts the SDK on a runner, which is why CI runs them and why
# nothing on CI ever noticed the assumption. This image's .NET lives at /usr/share/dotnet with
# a /usr/bin/dotnet symlink, so without this line those eight tests skip — with the honest but
# misleading reason "office analyser CLI or dotnet runtime not built/available", on an image
# whose entire job is to have built it.
#
# Measured, before and after this one ENV: 3416 passed / 47 skipped → 3424 passed / 39 skipped.
# It is the modules' own documented override, not a change to any test.
ENV ACP_DOTNET=/usr/bin/dotnet

# CI=true — turns a coverage gate ON, and is the one place in the tree that reads it
# (`grep -rn 'environ.get("CI")' tests/ api/ scripts/` returns exactly one hit).
#
# tests/test_docx_corpus_regression_gate.py::test_ocr_criteria_are_covered_in_ci asserts that
# tesseract is present, and skips itself off CI on the reasoning that "a dev box without
# tesseract should get an honest partial answer, not a red suite about a dependency it never
# agreed to install". This image is not that dev box: tesseract is installed above, and the
# build fails if it is not. Declaring CI makes the assertion run, so a future break in the
# tesseract layer shows up as a failing test here exactly as `Fail if OCR coverage was lost`
# shows it up in the workflow — instead of as a silent skip and 1.4.5/1.4.9 going unexercised.
#
# Note the direction: this ENABLES a check. Nothing in this image disables, quarantines or
# skips a test to make the log look better.
ENV CI=true

# Deliberately NOT setting ACP_OFFICE_CLI or ACP_PDF_ENGINE — unlike ACP_DOTNET above, those two
# have in-repo defaults that are already correct here. tests/engines.py reads both as OVERRIDES:
# the entrypoint builds the Office DLL to the canonical in-tree path, and the PDF engine is
# vendored at engine/pdf-analyser (ADR 0029). Setting them would make this image's
# OFFICE_OK/PDF_OK true for a reason a developer's own `dotnet build` could not reproduce, and
# nothing in a green log would mention it.
ENTRYPOINT ["acp-test-entrypoint"]
CMD ["python", "-m", "pytest", "tests/", "-q"]
