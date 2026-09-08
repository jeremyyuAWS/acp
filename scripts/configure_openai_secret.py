"""Provision a GitHub-held key without logging credentials or changing images."""
import json
import os
import subprocess
import urllib.request

APPS = ("acp-app", "acp-discovery", "acp-assess", "acp-remediate")
GROUP = "mdk-accessibility"
READY = "https://acp-app.greenwater-4bf2c997.eastus2.azurecontainerapps.io/readyz"


def require_idle():
    with urllib.request.urlopen(READY, timeout=20) as response:
        status = json.load(response)
    queue = status.get("queue", {})
    if status.get("ready") is not True or queue.get("available") is not True or queue.get("active") != 0:
        raise RuntimeError("Production is not idle and ready; retry configuration after jobs finish.")


def az(*args):
    # Azure errors can contain request details. Never forward stdout/stderr containing a key.
    result = subprocess.run(["az", *args, "--only-show-errors", "--output", "none"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError("Azure credential configuration failed; inspect resource health without printing secrets.")


def main():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("The GitHub OpenAI secret is absent.")
    require_idle()
    for app in APPS:
        az("containerapp", "secret", "set", "--resource-group", GROUP, "--name", app,
           "--secrets", "openai-api-key=" + key)
    for app in APPS:
        # Recheck before each revision update. Existing environment entries are retained.
        require_idle()
        az("containerapp", "update", "--resource-group", GROUP, "--name", app,
           "--set-env-vars", "OPENAI_API_KEY=secretref:openai-api-key")
        print(f"Credential reference configured for {app}; value not displayed.")


if __name__ == "__main__":
    main()
