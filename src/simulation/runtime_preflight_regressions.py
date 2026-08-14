"""Focused offline regressions for the runtime compatibility preflight."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import socket
from unittest.mock import patch

from src import runtime_preflight


def evaluate_runtime_preflight_regressions() -> dict[str, object]:
    failures: list[str] = []
    package_items = tuple(runtime_preflight.REQUIRED_RUNTIME_PACKAGES.items())

    if runtime_preflight.check_runtime((3, 12), ()):
        failures.append("supported Python 3.12 was rejected")
    if not any(
        "unsupported" in failure
        for failure in runtime_preflight.check_runtime((3, 11), ())
    ):
        failures.append("unsupported Python family was not rejected")
    if dict(package_items) != runtime_preflight.REQUIRED_RUNTIME_PACKAGES:
        failures.append("required dependency versions are not inspectable")

    network_attempts: list[object] = []

    def reject_network(*args: object, **kwargs: object) -> object:
        network_attempts.append((args, kwargs))
        raise AssertionError("network access attempted")

    with (
        patch.object(socket, "create_connection", reject_network),
        patch.object(socket.socket, "connect", reject_network),
    ):
        output = StringIO()
        with redirect_stdout(output):
            exit_code = runtime_preflight.main()
    rendered = output.getvalue()
    if exit_code != 0 or "PASS" not in rendered:
        failures.append("preflight success result is not deterministic")
    if network_attempts:
        failures.append("preflight attempted network access")
    if "OPENAI_API_KEY" in rendered or "fake-pilot-token" in rendered:
        failures.append("preflight output can expose secrets")

    return {"passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_runtime_preflight_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
