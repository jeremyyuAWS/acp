"""Quick check that the keyless ADC credential can read the corpus folder."""
import sys
import google.auth
from googleapiclient.discovery import build

FOLDER = "1W27ULZsstP7gYGzgKKBId0qEfNxeKn0_"
creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
svc = build("drive", "v3", credentials=creds, cache_discovery=False)
r = svc.files().list(
    q=f"'{FOLDER}' in parents and trashed=false",
    fields="files(name,mimeType,size)", pageSize=50, orderBy="name",
).execute()
fs = r.get("files", [])
print(f"connector read OK — {len(fs)} files in acp-demo-corpus:", flush=True)
for f in fs:
    print(f"  {f['name']:26} {int(f.get('size',0) or 0):>7} B", flush=True)
sys.stdout.flush()
