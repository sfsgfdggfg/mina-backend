from __future__ import annotations

from src.core.data_provenance import (
    DataProvenanceBlockedError,
    get_dataset_provenance,
    require_pilot_operational_dataset,
    validate_data_provenance_registry,
)


def evaluate_data_provenance_regressions() -> dict:
    failures: list[str] = []

    validation = validate_data_provenance_registry()

    if not validation.get("valid"):
        failures.append(
            "provenance registry should validate: "
            + "; ".join(validation.get("errors") or [])
        )

    supplier = get_dataset_provenance("supplier_capabilities")

    if supplier.get("classification") != "demo":
        failures.append(
            "current supplier capability data must be explicitly demo"
        )

    if supplier.get("pilot_usable") is not False:
        failures.append(
            "demo supplier capability data must not be pilot usable"
        )

    customer = get_dataset_provenance("customer_memory")

    if customer.get("pilot_usable") is not False:
        failures.append(
            "unverified customer memory must not be pilot usable"
        )

    commodity = get_dataset_provenance("commodity_dictionary")

    if commodity.get("classification") != "internal_reference":
        failures.append(
            "commodity dictionary must be labeled internal_reference"
        )

    development_env = {
        "MINAI_PILOT_MODE": "0",
    }

    try:
        require_pilot_operational_dataset(
            "supplier_capabilities",
            environ=development_env,
        )
    except Exception as exc:
        failures.append(
            "development mode should retain demo supplier data: "
            f"{type(exc).__name__}: {exc}"
        )

    pilot_env = {
        "MINAI_PILOT_MODE": "1",
    }

    try:
        require_pilot_operational_dataset(
            "supplier_capabilities",
            environ=pilot_env,
        )
    except DataProvenanceBlockedError:
        pass
    except Exception as exc:
        failures.append(
            "pilot supplier provenance raised wrong exception: "
            f"{type(exc).__name__}: {exc}"
        )
    else:
        failures.append(
            "pilot mode accepted unverified supplier capability data"
        )

    try:
        require_pilot_operational_dataset(
            "commodity_dictionary",
            environ=pilot_env,
        )
    except Exception as exc:
        failures.append(
            "internal reference data should remain usable in pilot: "
            f"{type(exc).__name__}: {exc}"
        )

    # In pilot mode, unverified customer memory must not enrich or
    # influence risk; required supplier master data must stop the workflow.
    import os
    from unittest.mock import patch

    from src.core.customer_memory import enrich_shipment_with_customer_memory
    from src.core.models import Shipment
    from src.workflow import pipeline

    pilot_shipment = Shipment(
        customer_name="Oğuz Gıda",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        transport_mode="road",
        cargo_ready_date="2026-08-13",
        is_adr=False,
        is_temperature_controlled=False,
    )

    with patch.dict(
        os.environ,
        {"MINAI_PILOT_MODE": "1"},
        clear=False,
    ):
        memory_result = enrich_shipment_with_customer_memory(
            shipment=pilot_shipment.model_copy(deep=True),
            sender_address="trusted@example.invalid",
        )

        if memory_result.matched:
            failures.append(
                "pilot mode consumed unverified customer-memory data"
            )

        if memory_result.identity_status != "provenance_unverified":
            failures.append(
                "unverified pilot customer memory was not explicitly labeled"
            )

        workflow_result = pipeline.process_shipment(
            shipment=pilot_shipment.model_copy(deep=True),
            email_text=(
                "Adana'dan Hamburg'a 20 ton tekstil yükü için "
                "komple tenteli araç fiyatı rica ederiz."
            ),
        )

        if workflow_result.get("result_type") != "data_provenance_blocked":
            failures.append(
                "pilot workflow did not stop on unverified supplier data"
            )

        if workflow_result.get("supplier_rfq_drafts"):
            failures.append(
                "pilot workflow generated RFQs from unverified supplier data"
            )

        if workflow_result.get("quote_approval") is not None:
            failures.append(
                "pilot workflow generated quote approval from "
                "unverified supplier data"
            )

        recommendation = workflow_result.get("action_recommendation")
        if (
            recommendation is None
            or recommendation.action_type != "data_provenance_blocked"
        ):
            failures.append(
                "pilot provenance block lacked explicit operator action"
            )

    # A pilot_verified label alone is insufficient. The verified
    # fingerprint must match the exact operational dataset bytes.
    import json
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        data_dir = temp_root / "data"
        data_dir.mkdir()

        supplier_file = data_dir / "supplier_capabilities.json"
        supplier_file.write_text(
            '[{"supplier_name":"Verified Test"}]',
            encoding="utf-8",
        )

        provenance_file = data_dir / "provenance_registry.json"
        provenance_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "datasets": {
                        "supplier_capabilities": {
                            "path": "data/supplier_capabilities.json",
                            "classification": "pilot_verified",
                            "operational": True,
                            "pilot_usable": True,
                            "verified_by": "Pilot Data Owner",
                            "verified_at": "2026-08-13T18:00:00+03:00",
                            "verified_sha256": "0" * 64,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        try:
            require_pilot_operational_dataset(
                "supplier_capabilities",
                environ={"MINAI_PILOT_MODE": "1"},
                path=provenance_file,
            )
        except DataProvenanceBlockedError:
            pass
        else:
            failures.append(
                "pilot accepted a dataset whose bytes did not match "
                "the verified fingerprint"
            )

        from src.core.data_provenance import calculate_dataset_sha256

        matching_registry = {
            "version": 1,
            "datasets": {
                "supplier_capabilities": {
                    "path": "data/supplier_capabilities.json",
                    "classification": "pilot_verified",
                    "operational": True,
                    "pilot_usable": True,
                    "verified_by": "Pilot Data Owner",
                    "verified_at": "2026-08-13T18:00:00+03:00",
                    "verified_sha256": calculate_dataset_sha256(
                        supplier_file
                    ),
                }
            },
        }

        provenance_file.write_text(
            json.dumps(matching_registry),
            encoding="utf-8",
        )

        try:
            require_pilot_operational_dataset(
                "supplier_capabilities",
                environ={"MINAI_PILOT_MODE": "1"},
                path=provenance_file,
            )
        except Exception as exc:
            failures.append(
                "pilot rejected correctly fingerprinted verified data: "
                f"{type(exc).__name__}: {exc}"
            )

    return {
        "name": "Pilot data provenance boundary",
        "passed": len(failures) == 0,
        "failures": failures,
    }
