from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from src.paths import REPO_ROOT
from src.pilot_profile_launcher import (
    PilotProfileConfigurationError,
    build_profile_environment,
    main,
    safe_profile_summary,
    validate_profile_files,
)
from src.simulation.physical_temp import physical_temporary_directory
from src.simulation.pilot_launcher_regressions import (
    _valid_env,
    _write_pilot_data_pack,
)


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "\n".join(
            f"{key}={json.dumps(value)}"
            for key, value in sorted(values.items())
        ) + "\n",
        encoding="utf-8",
    )

def evaluate_pilot_profile_launcher_regressions() -> dict[str, object]:
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        if not condition:
            failures.append(label)

    with physical_temporary_directory() as temporary:
        root = Path(temporary)
        pack = _write_pilot_data_pack(root / "pilot-pack")
        core_env = _valid_env(pack)
        core_env["MINAI_OUTBOUND_MODE"] = "shadow"
        core_env["OPENAI_API_KEY"] = "synthetic-api-key-fixture-value"
        core_path = root / "pilot.env"
        _write_env(core_path, core_env)

        web_overlay = {
            "MINAI_PILOT_PORT": "8443",
            "MINAI_PILOT_BASE_URL": "https://127.0.0.1:8443",
        }
        web_path = root / "web-pilot.env"
        _write_env(web_path, web_overlay)

        effective, sources = build_profile_environment(
            core_env_file=core_path,
            overlay_env_files=[web_path],
            base_environment={},
        )
        check(
            effective["MINAI_PILOT_DB_PATH"] == core_env["MINAI_PILOT_DB_PATH"]
            and effective["MINAI_PILOT_DATA_DIR"] == core_env["MINAI_PILOT_DATA_DIR"]
            and effective["MINAI_PILOT_PORT"] == "8443"
            and sources["MINAI_PILOT_DB_PATH"] == core_path.name
            and sources["MINAI_PILOT_PORT"] == web_path.name,
            "web overlay changes transport without changing core state/data profile",
        )

        legacy_core_path = root / "legacy-shell-pilot.env"
        _write_env(legacy_core_path, core_env)
        escaped_operators = "".join(
            ("\\" + char) if char in '{}" ' else char
            for char in core_env["MINAI_PILOT_OPERATORS_JSON"]
        )
        legacy_lines = legacy_core_path.read_text(encoding="utf-8").splitlines()
        legacy_lines = [
            (f"export MINAI_PILOT_OPERATORS_JSON={escaped_operators}"
             if line.startswith("MINAI_PILOT_OPERATORS_JSON=") else line)
            for line in legacy_lines
        ]
        legacy_core_path.write_text("\n".join(legacy_lines) + "\n", encoding="utf-8")
        legacy_effective, _ = build_profile_environment(
            core_env_file=legacy_core_path,
            base_environment={},
        )
        check(
            legacy_effective["MINAI_PILOT_OPERATORS_JSON"]
            == core_env["MINAI_PILOT_OPERATORS_JSON"],
            "legacy shell-escaped JSON env values normalize without exposing secrets",
        )

        smoke_overlay_path = root / "local-pilot.env"
        _write_env(
            smoke_overlay_path,
            {
                "MINAI_PILOT_DB_PATH": str(root / "smoke.db"),
                "MINAI_PILOT_DATA_DIR": str(root / "smoke-pack"),
            },
        )
        try:
            build_profile_environment(
                core_env_file=core_path,
                overlay_env_files=[smoke_overlay_path],
                base_environment={},
            )
        except PilotProfileConfigurationError:
            smoke_override_blocked = True
        else:
            smoke_override_blocked = False
        check(smoke_override_blocked, "smoke overlay cannot replace pilot DB/data profile")

        provider_overlay_path = root / "provider-overlay.env"
        _write_env(provider_overlay_path, {"MINAI_OUTLOOK_MAILBOX_ID": "wrong-mailbox"})
        try:
            build_profile_environment(
                core_env_file=core_path,
                overlay_env_files=[provider_overlay_path],
                base_environment={},
            )
        except PilotProfileConfigurationError:
            provider_override_blocked = True
        else:
            provider_override_blocked = False
        check(provider_override_blocked, "overlay cannot replace provider identity")

        summary = safe_profile_summary(effective, sources)
        encoded_summary = json.dumps(summary, sort_keys=True)
        check(
            "synthetic-api-key-fixture-value" not in encoded_summary
            and "MINAI_PILOT_OPERATORS_JSON" not in encoded_summary,
            "safe profile summary does not expose secrets or operator tokens",
        )

        validated = validate_profile_files(
            core_env_file=core_path,
            base_environment={},
        )
        check(
            validated["outbound_mode"] == "shadow"
            and validated["database_source"] == core_path.name,
            "core profile passes the normal controlled-pilot launcher preflight",
        )

        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--core-env", str(core_path), "--check-only"])
        check(
            code == 0
            and "synthetic-api-key-fixture-value" not in output.getvalue()
            and '"outbound_mode": "shadow"' in output.getvalue(),
            "check-only CLI validates and prints only a safe effective profile summary",
        )

    repo_env = REPO_ROOT / ".pilot-profile-regression.env"
    try:
        _write_env(
            repo_env,
            {
                "MINAI_PILOT_MODE": "true",
                "MINAI_PILOT_DB_PATH": "/tmp/pilot.sqlite3",
                "MINAI_PILOT_DATA_DIR": "/tmp/pilot-pack",
            },
        )
        try:
            build_profile_environment(
                core_env_file=repo_env,
                base_environment={},
            )
        except PilotProfileConfigurationError:
            repo_env_blocked = True
        else:
            repo_env_blocked = False
        check(repo_env_blocked, "profile env file inside repository is rejected")
    finally:
        repo_env.unlink(missing_ok=True)

    return {
        "name": "Controlled pilot deployment profile isolation",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_pilot_profile_launcher_regressions()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(0 if result["passed"] else 1)
