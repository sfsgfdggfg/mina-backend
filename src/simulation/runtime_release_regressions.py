"""Focused regressions for immutable runtime release identity."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from src.core import runtime_release


_SHA = "a" * 40
_PLATFORM_SHA = "b" * 40
_RAILWAY_ENV = {
    "RAILWAY_DEPLOYMENT_ID": "deployment-123",
    "RAILWAY_GIT_COMMIT_SHA": _PLATFORM_SHA,
    "RAILWAY_GIT_REPO_OWNER": "example-owner",
    "RAILWAY_GIT_REPO_NAME": "mina-backend",
    "RAILWAY_GIT_BRANCH": "main",
}


def evaluate_runtime_release_regressions() -> dict[str, object]:
    failures: list[str] = []

    with patch.object(runtime_release, "_git", return_value=None):
        identity = runtime_release.capture_runtime_release_identity(_RAILWAY_ENV)
    if not (
        identity.available
        and identity.commit_sha == _PLATFORM_SHA
        and identity.clean_worktree
    ):
        failures.append("Railway GitHub metadata did not provide immutable release identity")

    invalid = dict(_RAILWAY_ENV, RAILWAY_GIT_COMMIT_SHA="not-a-sha")
    with patch.object(runtime_release, "_git", return_value=None):
        identity = runtime_release.capture_runtime_release_identity(invalid)
    if identity.available or identity.commit_sha is not None or identity.clean_worktree:
        failures.append("invalid Railway commit metadata was accepted")

    incomplete = dict(_RAILWAY_ENV)
    incomplete.pop("RAILWAY_DEPLOYMENT_ID")
    with patch.object(runtime_release, "_git", return_value=None):
        identity = runtime_release.capture_runtime_release_identity(incomplete)
    if identity.available:
        failures.append("incomplete Railway GitHub context was accepted")

    head = subprocess.CompletedProcess(["git"], 0, stdout=_SHA + "\n", stderr="")
    dirty = subprocess.CompletedProcess(["git"], 0, stdout=" M src/api.py\n", stderr="")
    with patch.object(runtime_release, "_git", side_effect=[head, dirty]):
        identity = runtime_release.capture_runtime_release_identity(_RAILWAY_ENV)
    if not (
        identity.available
        and identity.commit_sha == _SHA
        and not identity.clean_worktree
    ):
        failures.append("Railway metadata masked a dirty local Git worktree")

    return {"passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_runtime_release_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
