"""The Azure DevOps credential helper must never blame the user for its own failure.

Two bugs, both of which presented as `fatal: Authentication failed for 'https://dev.azure.com/...'`
while the credentials were perfectly fine.

1. The helper ended with an unconditional

       token=$(az account get-access-token ... 2>/dev/null)
       echo "username=azuretoken"
       echo "password=$token"

   When `az` failed, `$token` was empty, `az`'s explanation had been discarded, and git read the
   empty password as a credential the server rejected. The helper now prints nothing on failure,
   explains on stderr, and exits non-zero.

2. macOS ships `credential.helper = osxkeychain` in Xcode's SYSTEM gitconfig, so it applies even
   with an empty ~/.gitconfig. It ran BEFORE this helper and git also STORED each minted token in
   the login keychain. The AAD token lives ~90 min; the keychain entry never expires. Git kept
   serving the stale token until Azure DevOps rejected it. setup-ado-auth.sh writes an empty
   `helper =` entry first, resetting the inherited chain for that URL only.

These tests drive the real script with a stubbed `az`. Nothing here contacts Azure.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "scripts" / "git-credential-ado.sh"
SETUP = ROOT / "scripts" / "setup-ado-auth.sh"

# A JWT-shaped stand-in. Only its shape matters; nothing decodes it here.
FAKE_TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiI0OTliODRhYyJ9.c2ln"

pytestmark = pytest.mark.skipif(not shutil.which("sh"), reason="POSIX sh required")


def _stub_az(tmp_path: Path, body: str) -> dict:
    """Put a fake `az` first on PATH and return an env dict for subprocess."""
    binn = tmp_path / "bin"
    binn.mkdir(exist_ok=True)
    az = binn / "az"
    az.write_text(body)
    az.chmod(0o755)
    return dict(os.environ, PATH=f"{binn}:{os.environ['PATH']}")


def _run(env, *args, stdin=""):
    return subprocess.run(["sh", str(HELPER), *args], input=stdin,
                          capture_output=True, text=True, env=env)


AZ_OK = f'#!/bin/sh\necho "{FAKE_TOKEN}"\nexit 0\n'
AZ_FAILS = "#!/bin/sh\necho \"ERROR: Please run 'az login' to setup account.\" >&2\nexit 1\n"
AZ_EMPTY = "#!/bin/sh\nexit 0\n"                      # exits 0, prints nothing


# ---------------------------------------------------------------- happy path

def test_get_emits_username_and_password(tmp_path):
    out = _run(_stub_az(tmp_path, AZ_OK), "get")
    assert out.returncode == 0, out.stderr
    assert "username=azuretoken" in out.stdout
    assert f"password={FAKE_TOKEN}" in out.stdout


@pytest.mark.parametrize("verb", ["store", "erase"])
def test_store_and_erase_are_silent_no_ops(tmp_path, verb):
    """Caching a 90-minute token is the bug. `store` must write nothing, anywhere."""
    out = _run(_stub_az(tmp_path, AZ_OK), verb)
    assert out.returncode == 0
    assert out.stdout == ""


# ---------------------------------------------------------------- the failure path

@pytest.mark.parametrize("az_body,label", [(AZ_FAILS, "az exits non-zero"),
                                           (AZ_EMPTY, "az exits 0 but prints nothing")])
def test_failure_never_emits_an_empty_password(tmp_path, az_body, label):
    """An empty `password=` is what git reports as 'Authentication failed'. Print nothing."""
    out = _run(_stub_az(tmp_path, az_body), "get")
    assert "password=" not in out.stdout, f"{label}: helper emitted a password line"
    assert out.stdout == "", f"{label}: helper wrote to stdout"
    assert out.returncode != 0, f"{label}: helper exited 0"


def test_failure_says_it_is_an_az_problem_not_a_credential_problem(tmp_path):
    out = _run(_stub_az(tmp_path, AZ_FAILS), "get")
    assert "NOT a rejected git credential" in out.stderr
    assert "az login" in out.stderr


def test_failure_surfaces_azs_own_stderr(tmp_path):
    """The original sent az's stderr to /dev/null, so the real reason was unknowable."""
    out = _run(_stub_az(tmp_path, AZ_FAILS), "get")
    assert "Please run 'az login' to setup account." in out.stderr


def test_missing_az_is_reported_clearly(tmp_path):
    # PATH must still resolve `sh` (we exec the helper through it) while resolving no `az`.
    # An empty PATH fails with FileNotFoundError before the helper ever runs, which proves
    # nothing. /bin and /usr/bin carry sh; az installs to /opt/homebrew/bin or /usr/local/bin.
    minimal = "/bin:/usr/bin"
    if shutil.which("az", path=minimal):
        pytest.skip("az is installed in /bin or /usr/bin; cannot construct an az-free PATH")
    env = dict(os.environ, PATH=minimal)
    out = _run(env, "get")
    assert out.returncode != 0
    assert "not on PATH" in out.stderr
    assert out.stdout == ""


# ---------------------------------------------------------------- retry

def test_a_transient_az_failure_is_retried(tmp_path):
    """Shared ~/.azure means an unrelated `az account set` can make one call fail."""
    counter = tmp_path / "n"
    az = (f'#!/bin/sh\n'
          f'n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "{counter}"\n'
          f'if [ "$n" -eq 1 ]; then echo "ERROR: profile in use" >&2; exit 1; fi\n'
          f'echo "{FAKE_TOKEN}"\n')
    out = _run(_stub_az(tmp_path, az), "get")
    assert out.returncode == 0, out.stderr
    assert f"password={FAKE_TOKEN}" in out.stdout
    assert counter.read_text().strip() == "2", "should have retried exactly once"


def test_retries_are_bounded(tmp_path):
    counter = tmp_path / "n"
    az = (f'#!/bin/sh\n'
          f'n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "{counter}"\n'
          f'echo "ERROR: always fails" >&2\nexit 1\n')
    out = _run(_stub_az(tmp_path, az), "get")
    assert out.returncode != 0
    assert counter.read_text().strip() == "3", "ATTEMPTS is 3; must not loop forever"


# ---------------------------------------------------------------- the token never lands on disk

def test_helper_writes_no_files(tmp_path):
    """It mints a bearer token. It must not leave one behind."""
    env = _stub_az(tmp_path, AZ_OK)
    home = tmp_path / "home"
    home.mkdir()
    env["HOME"] = str(home)
    before = set(home.rglob("*"))
    _run(env, "get")
    assert set(home.rglob("*")) == before, "helper created files under HOME"


# ---------------------------------------------------------------- portability
# The helper runs on developer macs (BSD userland) and in CI containers (GNU userland).

# GNU mktemp rejects a template with no XXXXXX; BSD mktemp accepts a bare prefix after -t.
# `mktemp -t gitcredado` therefore worked on macOS and died on the CI agent with
# "mktemp: too few X's in template".
_GNU_MKTEMP = r"""#!/bin/sh
for a in "$@"; do
  case "$a" in
    -*) echo "mktemp: gnu stub does not accept $a" >&2; exit 1 ;;
    *XXXXXX*) f=$(printf '%s' "$a" | sed "s/XXXXXX$/$$/"); : > "$f"; echo "$f"; exit 0 ;;
    *) echo "mktemp: too few X's in template '$a'" >&2; exit 1 ;;
  esac
done
echo "mktemp: no template" >&2; exit 1
"""


def test_helper_works_with_gnu_mktemp(tmp_path):
    """Regression: `mktemp -t NAME` is BSD-only. CI is GNU, and the helper died before az ran."""
    env = _stub_az(tmp_path, AZ_OK)
    mk = tmp_path / "bin" / "mktemp"
    mk.write_text(_GNU_MKTEMP)
    mk.chmod(0o755)
    out = _run(env, "get")
    assert "too few X's" not in out.stderr, out.stderr
    assert out.returncode == 0, out.stderr
    assert f"password={FAKE_TOKEN}" in out.stdout


def test_mktemp_template_is_portable():
    # Match INVOCATIONS -- `$(mktemp ...)` or a bare `mktemp ...` command -- not every line that
    # merely mentions mktemp, such as the "mktemp failed" error message.
    src = HELPER.read_text()
    mk = [ln for ln in src.splitlines()
          if re.search(r"(?:\$\(|^|;|&&|\|\|)\s*mktemp\s", ln) and not ln.lstrip().startswith("#")]
    assert mk, "no mktemp invocation found"
    for ln in mk:
        assert "XXXXXX" in ln, f"mktemp needs an explicit XXXXXX template (GNU): {ln.strip()}"
        assert not re.search(r"mktemp\s+-t\s+\S", ln), f"`mktemp -t NAME` is BSD-only: {ln.strip()}"


def test_helper_source_does_not_swallow_az_stderr():
    """`2>/dev/null` on the az call is the defect. It must not come back.

    Join backslash continuations first. The original helper wrote the call across three lines,
    so a per-line regex missed it entirely -- this assertion passed against the very code it was
    meant to reject until the mutation test exposed it.
    """
    src = HELPER.read_text().replace("\\\n", " ")
    az_calls = [ln for ln in src.splitlines()
                if re.search(r"\baz account get-access-token\b", ln)
                and not ln.lstrip().startswith("#")]
    assert az_calls, "could not find the az invocation"
    for ln in az_calls:
        assert "2>/dev/null" not in ln, f"az's stderr is being discarded again: {ln.strip()}"


# ---------------------------------------------------------------- the installer

def test_setup_script_resets_the_inherited_helper_chain():
    """Without the empty `helper =` reset, osxkeychain shadows this helper and caches the token."""
    src = SETUP.read_text()
    assert re.search(r'git config --global --add "\$URL_KEY" \'\'', src), \
        "setup must add an empty helper value first, to reset the inherited chain"
    add_empty = src.index("""--add "$URL_KEY" ''""")
    add_helper = src.index('--add "$URL_KEY" "!$DEST"')
    assert add_empty < add_helper, "the reset must come BEFORE the helper is added"


def test_setup_points_git_outside_the_working_tree():
    """A credential helper is machine-wide; a working tree is per-branch.

    Pointing git at $ACP/scripts/git-credential-ado.sh breaks every `git fetch` against Azure
    DevOps the moment someone checks out a branch created before the script existed -- including
    the fetch they would need to get it back. Install a copy to a stable path instead.
    """
    src = SETUP.read_text()
    assert 'DEST_DIR="${ACP_HELPER_DIR:-$HOME/.local/bin}"' in src, \
        "the installed helper must live outside the repo"
    assert 'git config --global --add "$URL_KEY" "!$DEST"' in src, \
        "git must be pointed at the installed copy, not the in-repo path"
    assert '--add "$URL_KEY" "!$SRC"' not in src, "must not point git into the working tree"
    assert 'install -m 0755 "$SRC" "$DEST"' in src, "the repo copy must be installed, executable"


def test_setup_reports_drift_between_repo_and_installed_copy():
    """The repo is the source of truth. A stale installed copy must be visible, not silent."""
    src = SETUP.read_text()
    assert 'cmp -s "$SRC" "$DEST"' in src
    assert "drift" in src.lower()


def test_setup_script_clears_a_cached_keychain_token():
    """A stale cached token is served until rejected, so the fix would look like it did nothing."""
    assert "git credential-osxkeychain erase" in SETUP.read_text()


def test_setup_scopes_the_reset_to_azure_devops_only():
    """GitHub and every other host must keep using the system osxkeychain helper."""
    src = SETUP.read_text()
    assert "credential.https://dev.azure.com.helper" in src
    assert "--unset-all credential.helper" not in src, "must not disturb the global helper"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_setup_check_mode_changes_nothing(tmp_path):
    """--check must be safe to run anywhere, including CI."""
    env = dict(os.environ, HOME=str(tmp_path), ACP_HELPER_DIR=str(tmp_path / "bin"))
    out = subprocess.run(["bash", str(SETUP), "--check"], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert "no changes made" in out.stdout
    assert not (tmp_path / ".gitconfig").exists(), "--check wrote to ~/.gitconfig"
    assert not (tmp_path / "bin").exists(), "--check installed the helper"


# `git` is stubbed so the installer cannot touch the real ~/.gitconfig or the login keychain.
_GIT_STUB = """#!/bin/sh
case "$1" in
  config) exit 0 ;;
  credential-osxkeychain) exit 0 ;;
  -C) shift 2; [ "$1" = "remote" ] && exit 1; exit 0 ;;
  *) exit 0 ;;
esac
"""


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_setup_installs_a_copy_outside_the_repo(tmp_path):
    """End-to-end: the installed helper is a real, executable copy at a stable path."""
    binn = tmp_path / "stub"
    binn.mkdir()
    (binn / "az").write_text(AZ_OK)
    (binn / "az").chmod(0o755)
    (binn / "git").write_text(_GIT_STUB)
    (binn / "git").chmod(0o755)

    dest_dir = tmp_path / "installed"
    env = dict(os.environ, HOME=str(tmp_path), ACP_HELPER_DIR=str(dest_dir),
               PATH=f"{binn}:{os.environ['PATH']}")
    out = subprocess.run(["bash", str(SETUP)], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stdout + out.stderr

    dest = dest_dir / "git-credential-ado.sh"
    assert dest.is_file(), "installer did not copy the helper"
    assert os.access(dest, os.X_OK), "installed helper is not executable"
    assert dest.read_text() == HELPER.read_text(), "installed copy differs from the repo copy"
    assert ROOT not in dest.parents, "installed helper is inside the working tree"


def test_both_scripts_are_executable():
    for p in (HELPER, SETUP):
        assert os.access(p, os.X_OK), f"{p.name} is not executable (git add --chmod=+x)"
