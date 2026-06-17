"""One-time OAuth to mint a read-only Drive token for the acp connector.

KEYLESS — no service-account key (sidesteps the iam.disableServiceAccountKeyCreation
org policy). Uses an OAuth 2.0 *Desktop* client, which that policy does NOT block.

Prereq: create an OAuth Desktop client in the test account's Cloud project and save
its JSON to .secrets/oauth-client.json (see instructions).

Run:
  uv run --with google-auth-oauthlib python scripts/drive_auth.py

Opens a browser; consent as the test account. Writes .secrets/drive-token.json
(a refresh token the connector reuses). Re-run only if you revoke or change scopes.
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SEC = Path(__file__).resolve().parent.parent / ".secrets"
client_file = SEC / "oauth-client.json"
token_file = SEC / "drive-token.json"

if not client_file.exists():
    raise SystemExit(f"missing {client_file} — create an OAuth Desktop client and save it there first")

flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
creds = flow.run_local_server(port=0)
token_file.write_text(creds.to_json())
print(f"✔ wrote {token_file} (read-only Drive refresh token; keyless)")
