"""Deterministic regressions for the authorized sanitized replay adapter."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.core.privacy import PrivacySafeText
from src.simulation.authorized_sanitized_replay import (
    AuthorizedReplayExecutionError,
    main as authorized_main,
    run_authorized_replay,
)
from src.simulation.pilot_rehearsal import (
    _snapshot,
    _write_synthetic_sources,
)
from src.simulation.sanitized_replay import (
    SCORED_FIELDS,
    ReplayCase,
)


def _fact(value):
    if value is None:
        return {"state": "unknown", "value": None}
    return {"state": "known", "value": value}


def _case(
    case_id: str,
    *,
    adr: bool | None,
    disposition: str,
    progression: bool,
) -> ReplayCase:
    base = _snapshot(adr=bool(adr))
    data = base.model_dump(mode="json")
    data["is_adr"] = adr
    facts = {
        field_name: _fact(data.get(field_name))
        for field_name in SCORED_FIELDS
        if field_name in data
    }
    expected = {
        "facts": facts,
        "disposition": disposition,
        "supplier_progression_expected": progression,
    }
    if disposition != "extraction_confirmation_required":
        expected["equipment"] = "Tenteli"
    return ReplayCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": case_id,
            "sender_address": "logistics@customer.invalid",
            "sender_domain": "customer.invalid",
            "subject": f"Synthetic authorized replay {case_id}",
            "body_text": (
                "Synthetic ADR TRUE road inquiry."
                if adr is True
                else (
                    "Synthetic ADR UNKNOWN road inquiry."
                    if adr is None
                    else "Synthetic ORDINARY road inquiry."
                )
            ),
            "expected": expected,
            "tags": ["synthetic", "authorized-replay-regression"],
        }
    )


def _synthetic_parser(
    safe_text: PrivacySafeText,
):
    if not isinstance(safe_text, PrivacySafeText):
        raise AssertionError("parser received non-privacy-safe text")
    if "ADR TRUE" in safe_text:
        return _snapshot(adr=True)
    if "ADR UNKNOWN" in safe_text:
        value = _snapshot(adr=False).model_dump()
        value["is_adr"] = None
        return type(_snapshot()).model_validate(value)
    return _snapshot(adr=False)


def _write_cases(path: Path, cases: list[ReplayCase]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                case.model_dump(mode="json"),
                ensure_ascii=False,
            )
            + "\n"
            for case in cases
        ),
        encoding="utf-8",
    )


def evaluate_authorized_sanitized_replay_regressions() -> dict:
    failures: list[str] = []

    def require(name: str, condition: bool) -> None:
        if not condition:
            failures.append(name)

    cases = [
        _case(
            "authorized-ordinary",
            adr=False,
            disposition="supplier_rfq_approval_required",
            progression=True,
        ),
        _case(
            "authorized-adr",
            adr=True,
            disposition="pilot_scope_excluded",
            progression=False,
        ),
        _case(
            "authorized-unknown-safety",
            adr=None,
            disposition="extraction_confirmation_required",
            progression=False,
        ),
    ]

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        sources = _write_synthetic_sources(root)
        source_paths = (
            sources.provenance_registry_path,
            sources.customer_memory_path,
            sources.supplier_capabilities_path,
        )
        before_sources = {
            path: path.read_bytes()
            for path in source_paths
        }
        previous_pilot_mode = os.environ.get("MINAI_PILOT_MODE")

        result = run_authorized_replay(
            cases,
            parser=_synthetic_parser,
            operational_data_sources=sources,
        )
        require(
            "three synthetic authorized cases executed",
            len(result.cases) == 3,
        )
        require(
            "authorized synthetic replay passes",
            result.passed
            and result.safety_critical_mismatches == 0,
        )
        require(
            "ordinary truth progresses only to RFQ approval",
            result.cases[0].actual_disposition
            == "supplier_rfq_approval_required"
            and result.cases[0].supplier_progression_correct is True,
        )
        require(
            "ADR truth remains pilot-scope excluded",
            result.cases[1].actual_disposition
            == "pilot_scope_excluded"
            and result.cases[1].supplier_progression_correct is True,
        )
        require(
            "unknown safety truth stops at extraction confirmation",
            result.cases[2].actual_disposition
            == "extraction_confirmation_required"
            and result.cases[2].supplier_progression_correct is True,
        )
        require(
            "operational sources are read-only during replay",
            before_sources
            == {
                path: path.read_bytes()
                for path in source_paths
            },
        )
        require(
            "pilot mode environment restored",
            os.environ.get("MINAI_PILOT_MODE")
            == previous_pilot_mode,
        )

        try:
            with patch(
                "src.simulation.authorized_sanitized_replay.route_allowed",
                return_value=True,
            ):
                run_authorized_replay(
                    cases,
                    parser=_synthetic_parser,
                    operational_data_sources=sources,
                )
        except AuthorizedReplayExecutionError as exc:
            outbound_blocked = (
                exc.code
                == "automated_outbound_must_remain_disabled"
            )
        else:
            outbound_blocked = False
        require(
            "enabled outbound policy blocks authorized replay",
            outbound_blocked,
        )

        fixture = root / "authorized-replay.jsonl"
        _write_cases(fixture, cases)

        missing_stderr = io.StringIO()
        with contextlib.redirect_stderr(missing_stderr):
            missing_rc = authorized_main(
                ["--input", str(fixture)]
            )
        require(
            "CLI requires explicit authorization confirmations",
            missing_rc == 2
            and "explicit_confirmation_required"
            in missing_stderr.getvalue(),
        )

        pack_root = root / "external-pack"
        data_dir = pack_root / "data"
        data_dir.mkdir(parents=True)
        _write_synthetic_sources(data_dir)
        cli_stdout = io.StringIO()
        cli_stderr = io.StringIO()
        with patch.dict(
            os.environ,
            {"MINAI_PILOT_DATA_DIR": str(pack_root)},
            clear=False,
        ):
            with patch(
                "src.simulation.authorized_sanitized_replay.parse_email_with_ai",
                _synthetic_parser,
            ):
                with contextlib.redirect_stdout(cli_stdout):
                    with contextlib.redirect_stderr(cli_stderr):
                        cli_rc = authorized_main(
                            [
                                "--input",
                                str(fixture),
                                "--confirm-pre-sanitized",
                                "--confirm-openai-data-use-approved",
                                "--confirm-no-autonomous-outbound",
                            ]
                        )
        output = cli_stdout.getvalue()
        require(
            "authorized CLI executes through injected parser boundary",
            cli_rc == 0
            and "Sanitized historical replay: PASS" in output,
        )
        require(
            "authorized CLI output omits replay values",
            "logistics@customer.invalid" not in output
            and "Synthetic ORDINARY road inquiry." not in output
            and "Synthetic Textile Customer" not in output
            and cli_stderr.getvalue() == "",
        )

    return {
        "name": "Authorized sanitized historical replay",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    print(evaluate_authorized_sanitized_replay_regressions())
