from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass

from src.paths import REPO_ROOT


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RAILWAY_GITHUB_CONTEXT_KEYS = (
    "RAILWAY_DEPLOYMENT_ID",
    "RAILWAY_GIT_REPO_OWNER",
    "RAILWAY_GIT_REPO_NAME",
    "RAILWAY_GIT_BRANCH",
)


@dataclass(frozen=True)
class RuntimeReleaseIdentity:
    available: bool
    commit_sha: str | None
    clean_worktree: bool


def _git(args: list[str]):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _railway_github_identity(
    environ: Mapping[str, str],
) -> RuntimeReleaseIdentity | None:
    sha = (environ.get("RAILWAY_GIT_COMMIT_SHA") or "").strip().lower()
    if not _COMMIT_RE.fullmatch(sha):
        return None
    if any(not (environ.get(key) or "").strip() for key in _RAILWAY_GITHUB_CONTEXT_KEYS):
        return None
    return RuntimeReleaseIdentity(
        available=True,
        commit_sha=sha,
        clean_worktree=True,
    )


def capture_runtime_release_identity(
    environ: Mapping[str, str] | None = None,
) -> RuntimeReleaseIdentity:
    env = os.environ if environ is None else environ
    head = _git(["rev-parse", "HEAD"])
    status = _git(["status", "--porcelain"])

    if head is not None and status is not None:
        sha = head.stdout.strip().lower()
        if (
            head.returncode == 0
            and status.returncode == 0
            and _COMMIT_RE.fullmatch(sha)
        ):
            return RuntimeReleaseIdentity(
                available=True,
                commit_sha=sha,
                clean_worktree=(status.stdout == ""),
            )

    railway_identity = _railway_github_identity(env)
    if railway_identity is not None:
        return railway_identity

    return RuntimeReleaseIdentity(
        available=False,
        commit_sha=None,
        clean_worktree=False,
    )


RUNTIME_RELEASE_IDENTITY = capture_runtime_release_identity()


def runtime_release_payload():
    identity = RUNTIME_RELEASE_IDENTITY
    return {
        "available": identity.available,
        "commit_sha": identity.commit_sha,
        "clean_worktree": identity.clean_worktree,
    }
