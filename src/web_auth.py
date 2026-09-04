from __future__ import annotations

import sys
from getpass import getpass

from src.core.web_session import hash_password


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["hash-password"]:
        print("Usage: python -m src.web_auth hash-password")
        return 2
    first = getpass("Web-shell password: ")
    second = getpass("Repeat password: ")
    if first != second:
        print("Passwords do not match.")
        return 1
    try:
        encoded = hash_password(first)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
