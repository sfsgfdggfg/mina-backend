"""Deterministic regressions for the authorized sanitized replay adapter."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.ai.email_parser import _apply_gtip_safety_overrides
from src.core.gtip import has_gtip_commodity_conflict
from src.core.models import Package
from src.core.privacy import PrivacySafeText
from src.simulation.authorized_sanitized_replay import (
    AuthorizedReplayExecutionError,
    _proposal_facts,
    main as authorized_main,
    run_authorized_replay,
)
from src.simulation.replay_receipt import ReleaseIdentity
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
        and not (
            field_name in {"gtip_commodity_conflict", "top_loading_required", "contractual_transit_risk"}
            and data.get(field_name) is not True
        )
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
    if "CONTRACT RISK" in safe_text:
        return _snapshot(adr=False).model_copy(
            update={"special_notes": "Guaranteed transit time. Delay penalty applies."}
        )
    if "TOP LOADING" in safe_text:
        return _snapshot(adr=False).model_copy(
            update={"special_notes": "Tavan vinci ile üstten yükleme gereklidir."}
        )
    if "GTIP CONFLICT" in safe_text:
        proposal = _snapshot(adr=False).model_copy(
            update={"commodity": "Plastik Ürünler"}
        )
        return _apply_gtip_safety_overrides(
            proposal,
            "Synthetic GTIP CONFLICT road inquiry. Commodity: Plastik Ürünler. GTIP: 850421000000.",
        )
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

    overlength_proposal = _snapshot(adr=False).model_copy(
        update={
            "packages": [
                Package(
                    package_type="machine", quantity=1, length_cm=1361,
                    width_cm=80, height_cm=150, weight_kg=5000,
                )
            ]
        }
    )
    require(
        "authorized replay derives overlength project truth from shared road dimensions",
        _proposal_facts(overlength_proposal).get("is_oversize_or_project") is True,
    )
    boundary_proposal = _snapshot(adr=False).model_copy(
        update={
            "packages": [
                Package(
                    package_type="machine", quantity=1, length_cm=1360,
                    width_cm=80, height_cm=150, weight_kg=5000,
                )
            ]
        }
    )
    require(
        "authorized replay does not overclassify exact 13.60m boundary",
        _proposal_facts(boundary_proposal).get("is_oversize_or_project") is not True,
    )

    nonstandard_height_proposal = _snapshot(adr=False).model_copy(
        update={
            "packages": [
                Package(
                    package_type="machine", quantity=1, length_cm=500,
                    width_cm=200, height_cm=286, weight_kg=5000,
                )
            ]
        }
    )
    require(
        "authorized replay derives non-standard 2.85m-plus height truth from shared road dimensions",
        _proposal_facts(nonstandard_height_proposal).get("is_oversize_or_project") is True,
    )
    standard_height_boundary = _snapshot(adr=False).model_copy(
        update={
            "packages": [
                Package(
                    package_type="machine", quantity=1, length_cm=500,
                    width_cm=200, height_cm=285, weight_kg=5000,
                )
            ]
        }
    )
    require(
        "authorized replay does not overclassify exact 2.85m height boundary",
        _proposal_facts(standard_height_boundary).get("is_oversize_or_project") is not True,
    )

    gtip_conflict_proposal = _apply_gtip_safety_overrides(
        _snapshot(adr=False).model_copy(
            update={"commodity": "Plastik Ürünler"}
        ),
        "Synthetic GTIP CONFLICT road inquiry. Commodity: Plastik Ürünler. GTIP: 850421000000.",
    )
    require(
        "authorized replay parser records structured GTIP commodity conflict evidence",
        has_gtip_commodity_conflict(gtip_conflict_proposal)
        and gtip_conflict_proposal.gtip_commodity_conflict is True
        and _proposal_facts(gtip_conflict_proposal).get("gtip_commodity_conflict") is True,
    )
    compatible_gtip_proposal = _apply_gtip_safety_overrides(
        _snapshot(adr=False).model_copy(
            update={"commodity": "İçecek / Meşrubat"}
        ),
        "Synthetic compatible GTIP road inquiry. Commodity: İçecek / Meşrubat. GTIP: 220210000000.",
    )
    require(
        "authorized replay does not invent GTIP conflict on compatible evidence",
        not has_gtip_commodity_conflict(compatible_gtip_proposal)
        and _proposal_facts(compatible_gtip_proposal).get("gtip_commodity_conflict") is not True,
    )

    conflict_data = gtip_conflict_proposal.model_dump(mode="json")
    conflict_facts = {
        field_name: _fact(conflict_data.get(field_name))
        for field_name in SCORED_FIELDS
        if field_name in conflict_data
        and not (
            field_name in {"gtip_commodity_conflict", "top_loading_required", "contractual_transit_risk"}
            and conflict_data.get(field_name) is not True
        )
    }
    top_loading_proposal = _snapshot(adr=False).model_copy(
        update={"special_notes": "Tavan vinci ile üstten yükleme gereklidir."}
    )
    require(
        "authorized replay derives structured top-loading evidence from proposal notes",
        _proposal_facts(top_loading_proposal).get("top_loading_required") is True,
    )
    top_loading_data = top_loading_proposal.model_dump(mode="json")
    top_loading_facts = {
        field_name: _fact(top_loading_data.get(field_name))
        for field_name in SCORED_FIELDS
        if field_name in top_loading_data
        and not (
            field_name in {"gtip_commodity_conflict", "top_loading_required", "contractual_transit_risk"}
            and top_loading_data.get(field_name) is not True
        )
    }
    top_loading_facts["top_loading_required"] = _fact(True)
    top_loading_case = ReplayCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": "authorized-top-loading",
            "sender_address": "logistics@customer.invalid",
            "sender_domain": "customer.invalid",
            "subject": "Synthetic authorized replay top loading",
            "body_text": "Synthetic TOP LOADING road inquiry.",
            "expected": {
                "facts": top_loading_facts,
                "disposition": "pilot_scope_excluded",
                "equipment": "Open Trailer / Platform",
                "supplier_progression_expected": False,
            },
            "tags": ["synthetic", "authorized-replay-regression", "top-loading"],
        }
    )

    contractual_risk_proposal = _snapshot(adr=False).model_copy(
        update={"special_notes": "Guaranteed transit time. Delay penalty applies."}
    )
    require(
        "authorized replay derives structured contractual transit risk evidence",
        _proposal_facts(contractual_risk_proposal).get("contractual_transit_risk") is True,
    )
    contractual_data = contractual_risk_proposal.model_dump(mode="json")
    contractual_facts = {
        field_name: _fact(contractual_data.get(field_name))
        for field_name in SCORED_FIELDS
        if field_name in contractual_data
        and not (
            field_name in {"gtip_commodity_conflict", "top_loading_required", "contractual_transit_risk"}
            and contractual_data.get(field_name) is not True
        )
    }
    contractual_facts["contractual_transit_risk"] = _fact(True)
    contractual_case = ReplayCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": "authorized-contract-risk",
            "sender_address": "logistics@customer.invalid",
            "sender_domain": "customer.invalid",
            "subject": "Synthetic authorized replay contract risk",
            "body_text": "Synthetic CONTRACT RISK road inquiry.",
            "expected": {
                "facts": contractual_facts,
                "disposition": "management_review",
                "supplier_progression_expected": False,
            },
            "tags": ["synthetic", "authorized-replay-regression", "contract-risk"],
        }
    )

    gtip_conflict_case = ReplayCase.model_validate(
        {
            "schema_version": "1.0",
            "case_id": "authorized-gtip-conflict",
            "sender_address": "logistics@customer.invalid",
            "sender_domain": "customer.invalid",
            "subject": "Synthetic authorized replay GTIP conflict",
            "body_text": "Synthetic GTIP CONFLICT road inquiry.",
            "expected": {
                "facts": conflict_facts,
                "disposition": "pilot_scope_excluded",
                "equipment": "Tenteli",
                "supplier_progression_expected": False,
            },
            "tags": ["synthetic", "authorized-replay-regression", "gtip-conflict"],
        }
    )

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
        gtip_conflict_case,
        top_loading_case,
        contractual_case,
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
            "six synthetic authorized cases executed",
            len(result.cases) == 6,
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
            "operator-confirmed GTIP conflict remains pilot-scope excluded downstream",
            result.cases[3].actual_disposition == "pilot_scope_excluded"
            and result.cases[3].supplier_progression_correct is True
            and result.cases[3].passed_safety,
        )
        require(
            "operator-confirmed top-loading requirement remains pilot-scope excluded downstream",
            result.cases[4].actual_disposition == "pilot_scope_excluded"
            and result.cases[4].equipment_correct is True
            and result.cases[4].supplier_progression_correct is True
            and result.cases[4].passed_safety,
        )
        require(
            "operator-confirmed contractual transit risk remains management-review blocked downstream",
            result.cases[5].actual_disposition == "management_review"
            and result.cases[5].supplier_progression_correct is True
            and result.cases[5].passed_safety,
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
                == "legacy_quote_prepare_send_must_remain_disabled"
            )
        else:
            outbound_blocked = False
        require(
            "legacy quote prepare-send policy blocks authorized replay",
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
        mutation_receipt = root / "mutation-receipt.json"
        mutation_calls = {"count": 0}

        def mutating_parser(safe_text):
            mutation_calls["count"] += 1
            if mutation_calls["count"] == 1:
                fixture.write_text(
                    fixture.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
            return _synthetic_parser(safe_text)

        with patch.dict(
            os.environ,
            {"MINAI_PILOT_DATA_DIR": str(pack_root)},
            clear=False,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                with contextlib.redirect_stderr(io.StringIO()):
                    mutation_rc = authorized_main(
                        [
                            "--input", str(fixture),
                            "--confirm-pre-sanitized",
                            "--confirm-openai-data-use-approved",
                            "--confirm-no-autonomous-outbound",
                            "--receipt", str(mutation_receipt),
                        ],
                        parser_func=mutating_parser,
                        release_identity_func=lambda: ReleaseIdentity("a" * 40, True),
                    )
        require(
            "replay source mutation blocks receipt",
            mutation_rc == 2 and not mutation_receipt.exists(),
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
