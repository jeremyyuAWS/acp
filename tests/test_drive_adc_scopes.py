"""What `google.auth.default(scopes=...)` actually does to the ADC credential.

`scanner._drive_service(None)` and `core.drive_service(None)` both take the ADC path and
both pass an explicit Drive scope list. Reading that code, the natural conclusion is "the
sweep runs with drive.readonly". For the credential this deployment ships it is false, and
that is why a scheduled sweep dies on Google's

    403 "Request had insufficient authentication scopes."

while the code that asks for the scope looks correct. `google.auth.default()` deliberately
withholds `scopes=` from the credential loader and then relies on `with_scopes_if_required`,
which is a NO-OP for a user credential (`requires_scopes` is False) — see the comment at
google/auth/_default.py, "Avoid passing scopes here to prevent passing scopes to user
credentials". A user credential's scopes are fixed at consent time; the client cannot widen
them, and nothing in the app can tell it has been handed a narrow token until Drive answers
403.

The container reaches this path via GOOGLE_APPLICATION_CREDENTIALS: deploy/public/Dockerfile
writes $ACP_GOOGLE_ADC to /tmp/adc.json and exports it (same in worker-entry.sh), and
deploy/public/deploy.sh sources that value from
~/.config/gcloud/application_default_credentials.json by default — a `gcloud auth
application-default login` file, i.e. type "authorized_user".

Consequence for operations: no code change can widen the sweep's Drive access. Either the
account behind the ADC re-consents with the Drive scope, or the deployment moves to a
service-account credential (which does honour `scopes=` — pinned below).
"""
from __future__ import annotations

import json

import google.auth
import pytest

DRIVE_RO = "https://www.googleapis.com/auth/drive.readonly"

# A user ("authorized_user") ADC file — what `gcloud auth application-default login` writes.
# Values are placeholders; nothing here is ever exchanged with Google.
_USER_ADC = {
    "type": "authorized_user",
    "client_id": "placeholder.apps.googleusercontent.com",
    "client_secret": "placeholder-not-a-secret",
    "refresh_token": "placeholder-not-a-token",
}


@pytest.fixture()
def user_adc_env(tmp_path, monkeypatch):
    """Point ADC at an authorized_user file, exactly as the container does."""
    path = tmp_path / "adc.json"
    path.write_text(json.dumps(_USER_ADC))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))
    # google.auth.default() consults these before the ADC file; clear them so the test
    # cannot accidentally resolve a real credential on a developer machine.
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GCLOUD_PROJECT", raising=False)
    return path


def test_default_drops_the_requested_scopes_for_a_user_adc(user_adc_env):
    """The `scopes=` argument does NOT reach an authorized_user credential.

    This is the mechanism behind the 403. `google.auth.default(scopes=[drive.readonly])`
    returns a credential carrying no scopes at all, so the access token it mints has only
    whatever was granted at `gcloud auth application-default login` time.
    """
    creds, _ = google.auth.default(scopes=[DRIVE_RO])

    assert creds.requires_scopes is False, (
        "if this ever becomes True, with_scopes_if_required would apply the requested "
        "scopes and the diagnosis in this module's docstring no longer holds — re-derive it"
    )
    # The requested scope did not stick. This is the whole finding.
    assert creds.scopes is None
    assert not creds.has_scopes([DRIVE_RO])


def test_load_from_file_does_apply_scopes_and_is_the_wrong_thing_to_conclude_from(user_adc_env):
    """Guard against the near-miss reading of the above.

    `load_credentials_from_file(..., scopes=...)` DOES set `_scopes` on the very same
    authorized_user credential — it passes them straight to `from_authorized_user_info`.
    So "user credentials ignore scopes" is not true in general; it is true specifically of
    `google.auth.default()`, which is the function the app calls. Pinned because reading
    only the general claim leads to the wrong fix.
    """
    creds, _ = google.auth.load_credentials_from_file(str(user_adc_env), scopes=[DRIVE_RO])

    assert creds.has_scopes([DRIVE_RO])
    # ...and it is still not a grant: `scopes` here is a request made at refresh time, which
    # the authorization server is free to refuse. `requires_scopes` is unchanged.
    assert creds.requires_scopes is False


def test_service_account_adc_does_take_the_requested_scopes(tmp_path, monkeypatch):
    """Contrast: a service-account credential DOES accept `scopes=` from default().

    Same call site, same argument, opposite outcome — which is why "the code requests
    drive.readonly" says nothing about the token until you know the ADC's credential type.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    info = {
        "type": "service_account",
        "project_id": "placeholder",
        "private_key_id": "0" * 40,
        "private_key": key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        "client_email": "placeholder@placeholder.iam.gserviceaccount.com",
        "client_id": "0" * 21,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    path = tmp_path / "sa.json"
    path.write_text(json.dumps(info))
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(path))

    creds, _ = google.auth.default(scopes=[DRIVE_RO])

    # A service account is scoped by the caller: `_get_service_account_credentials` takes
    # `scopes=` directly, so the scope is on the credential before `with_scopes_if_required`
    # is even consulted. (`requires_scopes` is False here too, but for the opposite reason —
    # it reads `not self._scopes`, and the scopes are already set. Assert the outcome, not
    # the flag.)
    assert creds.scopes == [DRIVE_RO]
    assert creds.has_scopes([DRIVE_RO])


@pytest.mark.parametrize("module_name,attr", [("scanner", "SCOPES"), ("core", "DRIVE_SCOPES")])
def test_both_adc_call_sites_ask_for_a_scope_they_cannot_grant_themselves(module_name, attr):
    """Both ADC call sites pass a Drive scope. Neither can make a user ADC honour it.

    Pinned so a future change that switches the deployment to a service account (or to the
    ADR 0017 auth-code flow) has a test saying what the scope list was for.
    """
    mod = pytest.importorskip(module_name)
    assert DRIVE_RO in getattr(mod, attr)


# ── the diagnostic that answers this without guessing ──────────────────────────

@pytest.fixture()
def app_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "owner@example.com", raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)
    client = TestClient(app)
    return lambda email: (client.headers.update({"Authorization": f"Bearer {email}"}), client)[1]


def test_the_scope_diagnostic_is_owner_only(app_client):
    """It reports on the deployment's server-side credential. Not a tenant's business."""
    assert app_client("someone@example.com").get("/drive/adc-scopes").status_code == 403


def test_the_scope_diagnostic_reports_a_missing_adc_rather_than_500ing(app_client, monkeypatch):
    """On a dev box with no ADC at all it must still answer."""
    import google.auth
    monkeypatch.setattr(google.auth, "default",
                        lambda **k: (_ for _ in ()).throw(RuntimeError("could not find ADC")))

    body = app_client("owner@example.com").get("/drive/adc-scopes").json()

    assert body["available"] is False and body["reason"] == "no_adc"
    assert DRIVE_RO in body["scopes_requested"]


def test_the_scope_diagnostic_names_the_missing_scope_and_the_ops_fix(app_client, monkeypatch):
    """The shape the operator reads: what Google actually granted, and what to do about it.

    Simulates the live failure — a credential granted cloud-platform but not Drive.
    """
    import google.auth
    import routes.drive as drive_routes

    class _Creds:
        scopes = None                     # the silent-drop signature
        token = "placeholder"

        def refresh(self, request):       # pretend the refresh succeeds
            return None

    monkeypatch.setattr(google.auth, "default", lambda **k: (_Creds(), "some-project"))
    # No raising=False: if the seam is renamed, this test must fail rather than silently start
    # calling Google from the suite.
    monkeypatch.setattr(drive_routes, "_tokeninfo_scopes",
                        lambda token: ["https://www.googleapis.com/auth/cloud-platform"])

    body = app_client("owner@example.com").get("/drive/adc-scopes").json()

    assert body["available"] is True
    assert body["scopes_granted"] == ["https://www.googleapis.com/auth/cloud-platform"]
    assert DRIVE_RO in body["missing_scopes"]
    assert body["sufficient_for_all_drives_listing"] is False
    # The fix is re-consent by the ADC's own account — not a config change or a redeploy.
    assert "re-consent" in body["remediation"]
    assert "application-default login" in body["remediation"]
