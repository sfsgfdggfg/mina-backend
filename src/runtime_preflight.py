"""Offline compatibility check for the controlled-pilot runtime."""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
import sys
from typing import Iterable


SUPPORTED_PYTHON_FAMILY = (3, 12)
REQUIRED_RUNTIME_PACKAGES: dict[str, str] = {
    "fastapi": "0.141.1",
    "openai": "2.53.0",
    "pydantic": "2.13.4",
    "python-dotenv": "1.2.2",
    "requests": "2.34.2",
    "uvicorn": "0.52.1",
}
IMPORT_NAMES: dict[str, str] = {"python-dotenv": "dotenv"}


def check_runtime(
    python_version: tuple[int, int] | None = None,
    packages: Iterable[tuple[str, str]] | None = None,
) -> list[str]:
    """Return deterministic compatibility failures without network access."""
    actual_python = python_version or sys.version_info[:2]
    failures: list[str] = []
    if actual_python != SUPPORTED_PYTHON_FAMILY:
        failures.append(
            "Python %d.%d is unsupported; expected Python %d.%d"
            % (*actual_python, *SUPPORTED_PYTHON_FAMILY)
        )

    package_items = REQUIRED_RUNTIME_PACKAGES.items() if packages is None else packages
    for distribution, expected_version in package_items:
        import_name = IMPORT_NAMES.get(distribution, distribution)
        try:
            import_module(import_name)
            actual_version = version(distribution)
        except (ImportError, PackageNotFoundError):
            failures.append(f"{distribution} is not installed")
            continue
        if actual_version != expected_version:
            failures.append(
                f"{distribution}=={actual_version} is unsupported; expected {expected_version}"
            )
    return failures


def main() -> int:
    failures = check_runtime()
    if failures:
        print("Runtime preflight: FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Runtime preflight: PASS (Python 3.12; locked runtime packages available)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
