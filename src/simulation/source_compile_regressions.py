"""Syntax gate for Python source shipped in the repository."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _source_files() -> list[Path]:
    files: list[Path] = []

    for root_name in ("src", "ui"):
        root = REPO_ROOT / root_name
        if root.exists():
            files.extend(root.rglob("*.py"))

    root_main = REPO_ROOT / "main.py"
    if root_main.exists():
        files.append(root_main)

    return sorted(set(files))


def evaluate_source_compile_regressions() -> dict:
    failures: list[str] = []

    for path in _source_files():
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (SyntaxError, UnicodeError):
            failures.append(
                str(path.relative_to(REPO_ROOT))
            )

    return {
        "name": "Python source compilation",
        "passed": len(failures) == 0,
        "failures": failures,
    }
