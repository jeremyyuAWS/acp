"""Mint a drive.file-scope OAuth token for the lifecycle test seeder.

This is a separate token from the read-only connector token (.secrets/drive-token.json).
drive.file scope limits writes to files this app creates or opens — it cannot touch
files owned by others. That is exactly what seed_lifecycle_test_files.py needs.

Prereq: the same OAuth Desktop client JSON used by drive_auth.py works here.
  .secrets/oauth-client.json  — Desktop OAuth client credentials

Run:
  uv run --with google-auth-oauthlib python scripts/drive_auth_write.py

Opens a browser; consent as the Drive account you want to seed test files into.
Writes .secrets/drive-write-token.json (kept separate from the read-only token).

Re-run only if you revoke access or the token expires (refresh tokens are long-lived).
"""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
SEC = Path(__file__).resolve().parent.parent / ".secrets"
client_file = SEC / "oauth-client.json"
token_file = SEC / "drive-write-token.json"

if not client_file.exists():
    raise SystemExit(
        f"missing {client_file}\n"
        "Create an OAuth Desktop client in the test account's Cloud project and save it there.\n"
        "Same client JSON as used by drive_auth.py — no new client needed."
    )

flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
creds = flow.run_local_server(port=0)
token_file.write_text(creds.to_json())
print(f"✔ wrote {token_file}")
print("  scope: drive.file (create/edit files this app touches; cannot read others' files)")
print(f"\nNext step:")
print(f"  uv run python scripts/seed_lifecycle_test_files.py [FOLDER_ID]")
