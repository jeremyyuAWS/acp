#!/usr/bin/env python3
"""Require a completed Azure CI build for the exact repository, main commit and definition."""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request


def validate_build(build: dict, *, commit: str, repository: str, definition: int) -> None:
    checks = {
        "completed CI": build.get("status") == "completed",
        "successful CI": build.get("result") == "succeeded",
        "requested commit": build.get("sourceVersion") == commit,
        "main branch": build.get("sourceBranch") == "refs/heads/main",
        "repository": build.get("repository", {}).get("id") == repository,
        "CI definition": build.get("definition", {}).get("id") == definition,
    }
    failed = [label for label, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Azure CI gate refused deployment: " + ", ".join(failed))


def main() -> None:
    commit = sys.argv[1]
    collection = os.environ["SYSTEM_COLLECTIONURI"].rstrip("/")
    parsed = urllib.parse.urlparse(collection)
    if parsed.scheme != "https" or parsed.hostname != "dev.azure.com":
        raise ValueError("Expected an HTTPS Azure DevOps collection URL")
    project = urllib.parse.quote(os.environ["SYSTEM_TEAMPROJECTID"], safe="")
    build_id = int(os.environ["ACP_AZURE_CI_RUN_ID"])
    definition = int(os.environ["ACP_AZURE_CI_DEFINITION_ID"])
    url = f"{collection}/{project}/_apis/build/builds/{build_id}?api-version=7.1"
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + os.environ["SYSTEM_ACCESSTOKEN"],
        "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        build = json.load(response)
    validate_build(build, commit=commit, repository=os.environ["BUILD_REPOSITORY_ID"],
                   definition=definition)
    print(f"Azure CI build {build_id} passed for {commit}")


if __name__ == "__main__":
    main()
