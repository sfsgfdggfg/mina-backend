"""Deterministic synthetic regressions for the sanitized replay harness."""

from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.core.pilot_store import DEFAULT_PILOT_DB_PATH, SQLitePilotStore
from src.simulation.pilot_rehearsal import _write_synthetic_sources
from src.simulation.sanitized_replay import (
    ReplayActual,
    ReplayValidationError,
    load_cases,
    main as replay_main,
    print_summary,
    replay_exit_code,
    run_replay,
)


def _fact(value=None, state="known"):
    return {"state": state, "value": value if state == "known" else None}


def _case(case_id: str, facts: dict, disposition: str, *, body="Sanitized freight inquiry.", equipment=None, progression=None):
    expected = {"facts": facts, "disposition": disposition}
    if equipment is not None:
        expected["equipment"] = equipment
    if progression is not None:
        expected["supplier_progression_expected"] = progression
    return {
        "schema_version": "1.0", "case_id": case_id,
        "sender_address": f"{case_id}@customer.invalid", "sender_domain": "customer.invalid",
        "subject": f"Synthetic inquiry {case_id}", "body_text": body,
        "expected": expected, "tags": ["synthetic"],
    }


def _fixtures():
    ordinary = {
        "customer_name": _fact("Synthetic Customer 01"), "pickup_country": _fact("Türkiye"),
        "pickup_city": _fact("Istanbul"), "delivery_country": _fact("Almanya"),
        "delivery_city": _fact("Hamburg"), "commodity": _fact("Tekstil"),
        "gross_weight_kg": _fact(20000), "service_type": _fact("FTL"),
        "transport_mode": _fact("road"), "equipment_type": _fact("Tenteli"),
        "is_adr": _fact(False), "is_temperature_controlled": _fact(False),
        "is_high_value": _fact(False),
    }
    rows = [
        _case("ordinary-ftl", ordinary, "supplier_rfq_approval_required", equipment="Tenteli", progression=True),
        _case("missing-weight", {**ordinary, "gross_weight_kg": _fact(None, "unknown")}, "clarification_required", progression=False),
        _case("ambiguous-package", {**ordinary, "gross_weight_kg": _fact(None, "unknown"), "packages": _fact(None, "unknown")}, "clarification_required", progression=False),
        _case("adr-stop", {**ordinary, "is_adr": _fact(True)}, "pilot_scope_excluded", progression=False),
        _case("reefer-stop", {**ordinary, "is_temperature_controlled": _fact(True), "temperature_requirement": _fact("2-8 C")}, "pilot_scope_excluded", progression=False),
        _case("non-road", {**ordinary, "transport_mode": _fact("sea")}, "pilot_scope_excluded", progression=False),
        _case("project-stop", {**ordinary, "is_oversize_or_project": _fact(True)}, "pilot_scope_excluded", progression=False),
        _case("unknown-commodity", {**ordinary, "commodity": _fact(None, "unknown")}, "clarification_required", progression=False),
        _case("unknown-truth", {**ordinary, "cargo_ready_date": _fact(None, "unknown")}, "supplier_rfq_approval_required", progression=True),
        _case("unexpected-inference", {**ordinary, "cargo_ready_date": _fact(None, "unknown")}, "supplier_rfq_approval_required", progression=True),
        _case("ordinary-mismatch", ordinary, "supplier_rfq_approval_required", progression=True),
        _case("safety-mismatch", {**ordinary, "is_adr": _fact(True)}, "pilot_scope_excluded", progression=False),
    ]
    return rows


def _actuals(cases):
    actuals = {}
    for case in cases:
        facts = {name: spec.value for name, spec in case.expected.facts.items()}
        actuals[case.case_id] = ReplayActual(
            facts=facts, disposition=case.expected.disposition,
            equipment=case.expected.equipment,
            supplier_progressed=bool(case.expected.supplier_progression_expected),
        )
    unexpected = dict(actuals["unexpected-inference"].facts)
    unexpected["cargo_ready_date"] = "2026-09-01"
    actuals["unexpected-inference"] = ReplayActual(unexpected, "supplier_rfq_approval_required", supplier_progressed=True)
    wrong = dict(actuals["ordinary-mismatch"].facts)
    wrong["delivery_city"] = "Berlin"
    actuals["ordinary-mismatch"] = ReplayActual(wrong, "supplier_rfq_approval_required", supplier_progressed=True)
    unsafe = dict(actuals["safety-mismatch"].facts)
    unsafe["is_adr"] = False
    actuals["safety-mismatch"] = ReplayActual(unsafe, "supplier_rfq_approval_required", supplier_progressed=True)
    return actuals


def _write(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _rejected(path: Path, category: str) -> bool:
    try:
        load_cases(path)
    except ReplayValidationError as exc:
        return exc.category == category
    return False


def _repository_data_snapshot(data_dir: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(data_dir): path.read_bytes()
        for path in data_dir.rglob("*") if path.is_file()
    }


def evaluate_sanitized_replay_regressions() -> dict:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    def require(name: str, condition: bool):
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    data_dir = Path("data")
    before = _repository_data_snapshot(data_dir)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        sources = _write_synthetic_sources(root)
        db_path = root / "sanitized-replay.sqlite3"
        store = SQLitePilotStore(db_path, run_id="synthetic-sanitized-replay")
        require("temporary SQLite only", db_path.exists() and db_path != DEFAULT_PILOT_DB_PATH and root in db_path.parents)
        require("synthetic operational sources only", all(
            path.parent == root for path in (
                sources.provenance_registry_path,
                sources.customer_memory_path,
                sources.supplier_capabilities_path,
            )
        ))
        del store
        fixture = root / "replay.jsonl"
        _write(fixture, _fixtures())
        cases = load_cases(fixture)
        actuals = _actuals(cases)

        network_attempts: list[str] = []

        def block_create_connection(*_args, **_kwargs):
            network_attempts.append("create_connection")
            raise AssertionError("network attempted")

        def block_socket_connect(*_args, **_kwargs):
            network_attempts.append("socket.connect")
            raise AssertionError("network attempted")

        with patch.object(socket, "create_connection", block_create_connection), patch.object(socket.socket, "connect", block_socket_connect):
            try:
                socket.create_connection(("example.invalid", 443))
            except AssertionError:
                pass
            try:
                # Call the patched descriptor directly so this never constructs a
                # real socket or reaches the network.
                socket.socket.connect(object(), ("example.invalid", 443))
            except AssertionError:
                pass
            result = run_replay(cases, lambda case: actuals[case.case_id])
        require("all synthetic scenarios executed", len(result.cases) == 12)
        require("ordinary FTL progression", not result.cases[0].mismatches)
        require("missing weight clarification", result.cases[1].clarification_correct)
        require("ambiguous package clarification", result.cases[2].clarification_correct)
        require("ADR fail closed baseline", result.cases[3].scope_correct)
        require("reefer fail closed baseline", result.cases[4].scope_correct)
        require("non-road excluded", result.cases[5].scope_correct)
        require("project cargo excluded", result.cases[6].scope_correct)
        require("unknown commodity clarification", result.cases[7].clarification_correct)
        unknown = next(item for item in result.cases[8].fields if item.field == "cargo_ready_date")
        require("unknown truth not extraction error", unknown.outcome == "correctly_unknown")
        require("unexpected inference identified", result.outcome_counts["unexpected_inference"] == 1)
        require("ordinary mismatch visible", result.grouped_mismatches["field:delivery_city"] == 1)
        require("safety mismatch fails aggregate", not result.passed and result.safety_critical_mismatches >= 1)
        require("safety mismatch produces nonzero", replay_exit_code(result) != 0)
        require("safety mismatch is separate", not result.cases[-1].passed_safety)
        require("ordinary mismatch is non-safety", result.cases[-2].passed_safety)
        require("network guards actively exercised", network_attempts == ["create_connection", "socket.connect"])

        output = io.StringIO()
        print_summary(result, output)
        safe_output = output.getvalue()
        require("safe aggregate output", "Sanitized replay summary" in safe_output and "Sanitized freight inquiry" not in safe_output and "@customer.invalid" not in safe_output)
        require("safe case failure output", "case=ordinary-mismatch category=delivery_city" in safe_output)
        require("no raw expected actual output", "Berlin" not in safe_output and "Synthetic Customer" not in safe_output)

        malformed = root / "malformed.jsonl"
        malformed.write_text('{"schema_version":"1.0"}\n', encoding="utf-8")
        require("malformed schema rejected", _rejected(malformed, "malformed_schema"))
        duplicate = root / "duplicate.jsonl"
        _write(duplicate, [_fixtures()[0], _fixtures()[0]])
        require("duplicate case id rejected", _rejected(duplicate, "duplicate_case_id"))
        for label, body, category in (
            ("email", "Contact person@example.com", "suspicious_email"),
            ("phone", "Call +90 555 123 45 67", "suspicious_phone"),
            ("iban", "TR33 0006 1005 1978 6457 8413 26", "suspicious_iban"),
        ):
            unsafe_path = root / f"unsafe-{label}.jsonl"
            _write(unsafe_path, [_case(f"unsafe-{label}", {}, "clarification_required", body=body)])
            require(f"unsanitized {label} rejected", _rejected(unsafe_path, category))

        unsafe_fact = root / "unsafe-expected-fact.jsonl"
        _write(unsafe_fact, [_case(
            "unsafe-expected-fact",
            {"commodity": _fact({"history": ["person@example.com"]})},
            "clarification_required",
        )])
        require("email in nested expected fact rejected", _rejected(unsafe_fact, "suspicious_email"))

        unsafe_tags = root / "unsafe-tags.jsonl"
        tagged_case = _case("unsafe-tags", {}, "clarification_required")
        tagged_case["tags"] = ["Call +90 555 123 45 67"]
        _write(unsafe_tags, [tagged_case])
        require("phone in tags rejected", _rejected(unsafe_tags, "suspicious_phone"))

        unsafe_metadata = root / "unsafe-expected-metadata.jsonl"
        _write(unsafe_metadata, [_case(
            "unsafe-expected-metadata", {}, "clarification_required",
            equipment="TR33 0006 1005 1978 6457 8413 26",
        )])
        require("IBAN in expected metadata rejected", _rejected(unsafe_metadata, "suspicious_iban"))

        safe_metadata = root / "safe-expected-metadata.jsonl"
        safe_case = _case(
            "safe-expected-metadata",
            {"commodity": _fact({"name": "Tekstil", "weights": [20000]})},
            "clarification_required", equipment="Tenteli",
        )
        safe_case["tags"] = ["road", "historical"]
        _write(safe_metadata, [safe_case])
        require("safe ordinary expected metadata accepted", len(load_cases(safe_metadata)) == 1)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            try:
                no_input = replay_main([])
            except SystemExit as exc:
                no_input = int(exc.code)
        require("missing input nonzero safe usage", no_input != 0 and "usage:" in stderr.getvalue() and "Traceback" not in stderr.getvalue())
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            external_result = replay_main(["--input", str(fixture)])
        require("external CLI validates without AI", external_result != 0 and "input accepted" in stdout.getvalue() and "authorized extraction adapter" in stdout.getvalue())
        require("outside repository accepted", root != Path.cwd() and len(cases) == 12)

        repository_path = Path.cwd() / "synthetic-replay-forbidden.jsonl"
        try:
            _write(repository_path, [_fixtures()[0]])
            require("repository replay path rejected", _rejected(repository_path, "repository_input_forbidden"))
        finally:
            repository_path.unlink(missing_ok=True)

    after = _repository_data_snapshot(data_dir)
    require("repository data unchanged", before == after)
    require("temporary fixtures removed", not Path(temporary).exists())
    source = Path(__file__).with_name("sanitized_replay.py").read_text(encoding="utf-8")
    require("no OpenAI dependency", "OpenAI(" not in source and "OPENAI_API_KEY" not in source)
    require("no default pilot DB", "DEFAULT_PILOT_DB_PATH" not in source and "minai_pilot.sqlite3" not in source)
    require("no outbound implementation", "smtplib" not in source and "requests." not in source and "httpx." not in source)
    return {"passed": not failures, "failures": failures, "checks": checks}


def main() -> int:
    result = evaluate_sanitized_replay_regressions()
    for name, passed in result["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"\nSanitized replay harness regressions: {'PASS' if result['passed'] else 'FAIL'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
