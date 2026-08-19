from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from src.paths import REPO_ROOT


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


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


def capture_runtime_release_identity():
    head = _git(["rev-parse", "HEAD"])
    status = _git(["status", "--porcelain"])

    if head is None or status is None:
        return RuntimeReleaseIdentity(
            available=False,
            commit_sha=None,
            clean_worktree=False,
        )

    sha = head.stdout.strip().lower()

    if (
        head.returncode != 0
        or status.returncode != 0
        or not _COMMIT_RE.fullmatch(sha)
    ):
        return RuntimeReleaseIdentity(
            available=False,
            commit_sha=None,
            clean_worktree=False,
        )

    return RuntimeReleaseIdentity(
        available=True,
        commit_sha=sha,
        clean_worktree=(status.stdout == ""),
    )


RUNTIME_RELEASE_IDENTITY = (
    capture_runtime_release_identity()
)


def runtime_release_payload():
    identity = RUNTIME_RELEASE_IDENTITY

    return {
        "available": identity.available,
        "commit_sha": identity.commit_sha,
        "clean_worktree": (
            identity.clean_worktree
        ),
    }
