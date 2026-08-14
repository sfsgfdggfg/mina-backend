"""Deterministic paths for repository-owned MINAI files."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


def data_path(*parts: str) -> Path:
    """Return a repository-owned path beneath ``data`` without using cwd."""
    return DATA_DIR.joinpath(*parts)
