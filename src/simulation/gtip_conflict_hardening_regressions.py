from __future__ import annotations

from src.ai.email_parser import _apply_gtip_safety_overrides
from src.core.gtip import (
    assess_gtip_commodity_consistency,
    has_gtip_commodity_conflict,
    is_gtip_commodity_conflict,
)
from src.simulation.runtime_authority_cutover_regressions import (
    _mail,
    _master_data,
    _shipment,
)
from src.workflow.pipeline import process_shipment


CONFLICT_TEXT = (
    "GTİP: 8504.21.00.00.00 olan plastik poşet yükümüz "
    "için fiyat rica ederiz."
)


def _run(shipment):
    return process_shipment(
        shipment=shipment,
        email_text=CONFLICT_TEXT,
        sender_address=_mail().sender_address,
        customer_subject="GTIP conflict regression",
        master_data_repository=_master_data(),
    )


def evaluate_gtip_conflict_hardening_regressions() -> dict:
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        if not condition:
            failures.append(label)

    shipment = _shipment()
    shipment.commodity = "Plastik Ürünler"
    shipment = _apply_gtip_safety_overrides(shipment, CONFLICT_TEXT)

    assessment = assess_gtip_commodity_consistency(
        shipment.gtip_code, shipment.commodity
    )
    check(
        shipment.commodity == "Plastik Ürünler"
        and shipment.gtip_code == "850421000000"
        and assessment["conflict"] is True
        and assessment["gtip_commodity"] == "Elektrik Transformatörü",
        "parser preserves explicit commodity while deriving GTIP conflict",
    )

    blocked = _run(shipment.model_copy(deep=True))
    blocked_consistency = blocked.get("operational_consistency") or {}
    blocked_readiness = blocked.get("quote_readiness")
    check(
        blocked_consistency.get("passed") is False
        and getattr(blocked_readiness, "result_type", None) == "blocked"
        and not (blocked.get("supplier_rfq_drafts") or [])
        and blocked.get("supplier_rfq_workflow") is None,
        "unresolved GTIP conflict blocks supplier RFQ and quote progression",
    )

    flag_removed = shipment.model_copy(
        update={"gtip_commodity_conflict": False, "gtip_detected_from_email": False},
        deep=True,
    )
    check(
        has_gtip_commodity_conflict(flag_removed) is True
        and (_run(flag_removed).get("operational_consistency") or {}).get("passed") is False,
        "current GTIP facts cannot bypass authority through missing legacy flags",
    )

    corrected = shipment.model_copy(
        update={"commodity": "Elektrik Transformatörü"}, deep=True
    )
    resolved = _run(corrected)
    check(
        has_gtip_commodity_conflict(corrected) is False
        and "GTIP CONSISTENCY WARNING" in (corrected.special_notes or "")
        and (resolved.get("operational_consistency") or {}).get("passed") is True
        and len(resolved.get("supplier_rfq_drafts") or []) == 1,
        "current confirmed facts clear a stale structured flag and warning after real correction",
    )

    check(
        is_gtip_commodity_conflict("Makine", "Elektrik Transformatörü") is False,
        "documented compatible commodity family remains non-conflicting",
    )

    return {
        "name": "GTIP commodity conflict hardening",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_gtip_conflict_hardening_regressions()
    print("PASS" if result["passed"] else "FAIL")
    for failure in result["failures"]:
        print("FAIL", failure)
    raise SystemExit(0 if result["passed"] else 1)
