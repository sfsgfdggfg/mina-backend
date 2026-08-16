"""Focused regressions for guided external pilot data-pack intake."""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

from src.pilot_data_pack import (
    initialize_pack,
    main as data_pack_main,
    validate_pack,
    verify_pack,
)
from src.pilot_data_pack_intake import (
    PilotDataPackIntakeError,
    add_customer_profile,
    add_supplier_profile,
    list_customer_profiles,
    list_supplier_profiles,
)


def _add_customer(
    paths,
    name: str,
    address: str,
) -> dict:
    return add_customer_profile(
        customer_memory_path=paths.customer_memory,
        provenance_registry_path=paths.provenance_registry,
        customer_name=name,
        trusted_sender_addresses=[address],
        default_commodity="Textile",
        default_equipment_type="Tenteli / Curtainsider",
        default_pickup_city="Adana",
        default_pickup_country="Türkiye",
        default_delivery_city="Hamburg",
        default_delivery_country="Almanya",
        operational_notes=["Synthetic guided intake."],
    )


def _add_supplier(
    paths,
    name: str,
    email: str,
) -> dict:
    return add_supplier_profile(
        supplier_capabilities_path=paths.supplier_capabilities,
        provenance_registry_path=paths.provenance_registry,
        supplier_name=name,
        role="primary",
        route_regions=["international"],
        countries=["Türkiye", "Almanya"],
        service_types=["FTL"],
        equipment_types=["Tenteli"],
        reliability_score=0.9,
        price_score=0.8,
        speed_score=0.8,
        notes="Synthetic guided intake.",
        primary_contact_email=email,
        priority_routes=["Türkiye-Almanya"],
    )


def evaluate_pilot_data_pack_intake_regressions() -> dict:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "pilot-pack"
        paths = initialize_pack(root)

        try:
            add_customer_profile(
                customer_memory_path=paths.customer_memory,
                provenance_registry_path=paths.provenance_registry,
                customer_name="No Trust Customer",
            )
        except PilotDataPackIntakeError:
            pass
        else:
            failures.append(
                "active customer intake did not require sender trust"
            )

        if json.loads(
            paths.customer_memory.read_text(encoding="utf-8")
        ) != []:
            failures.append(
                "rejected customer intake changed the dataset"
            )

        first = _add_customer(
            paths,
            "Synthetic Customer A",
            "ops-a@customer-a.invalid",
        )
        second = _add_customer(
            paths,
            "Synthetic Customer B",
            "ops-b@customer-b.invalid",
        )
        if (
            first.get("added") is not True
            or second.get("added") is not True
            or second.get("active_profile_count") != 2
        ):
            failures.append("guided customer intake did not persist")

        for index in range(3):
            result = _add_supplier(
                paths,
                f"Synthetic Supplier {index + 1}",
                f"rfq-{index + 1}@supplier-{index + 1}.invalid",
            )
            if result.get("added") is not True:
                failures.append(
                    "guided supplier intake did not persist"
                )

        customer_listing = list_customer_profiles(
            paths.customer_memory
        )
        supplier_listing = list_supplier_profiles(
            paths.supplier_capabilities
        )
        if (
            customer_listing.get("profile_count") != 2
            or supplier_listing.get("supplier_count") != 3
        ):
            failures.append("guided list summaries are incomplete")

        listing_text = json.dumps(
            {
                "customers": customer_listing,
                "suppliers": supplier_listing,
            }
        )
        if (
            "ops-a@customer-a.invalid" in listing_text
            or "rfq-1@supplier-1.invalid" in listing_text
        ):
            failures.append(
                "list summaries exposed contact addresses"
            )

        validation = validate_pack(root)
        if validation.get("valid") is not True:
            failures.append(
                "guided intake did not produce a valid pilot pack"
            )

        verified = verify_pack(
            root,
            verified_by="Synthetic Data Owner",
            confirm_final_reviewed=True,
        )
        if verified.get("verified") is not True:
            failures.append(
                "guided intake pack could not be verified"
            )

        try:
            _add_customer(
                paths,
                "Synthetic Customer C",
                "ops-c@customer-c.invalid",
            )
        except PilotDataPackIntakeError:
            pass
        else:
            failures.append(
                "verified pilot pack remained editable"
            )

        try:
            verify_pack(
                root,
                verified_by="Synthetic Data Owner",
                confirm_final_reviewed=True,
            )
        except ValueError:
            pass
        else:
            failures.append(
                "verification registry could be silently overwritten"
            )

    with tempfile.TemporaryDirectory() as cli_temporary:
        root = Path(cli_temporary) / "pilot-pack"
        initialize_pack(root)
        output = io.StringIO()

        customer_rc = data_pack_main(
            [
                "customer",
                "add",
                "--pack-dir",
                str(root),
                "--name",
                "CLI Customer",
                "--trusted-address",
                "ops@cli-customer.invalid",
            ],
            stream=output,
        )
        supplier_rc = data_pack_main(
            [
                "supplier",
                "add",
                "--pack-dir",
                str(root),
                "--name",
                "CLI Supplier",
                "--role",
                "primary",
                "--route-region",
                "international",
                "--country",
                "Türkiye",
                "--country",
                "Almanya",
                "--service-type",
                "FTL",
                "--equipment-type",
                "Tenteli",
                "--reliability-score",
                "0.9",
                "--price-score",
                "0.8",
                "--speed-score",
                "0.8",
                "--notes",
                "Synthetic CLI intake.",
                "--contact-email",
                "rfq@cli-supplier.invalid",
            ],
            stream=output,
        )
        customer_list_rc = data_pack_main(
            [
                "customer",
                "list",
                "--pack-dir",
                str(root),
            ],
            stream=output,
        )
        supplier_list_rc = data_pack_main(
            [
                "supplier",
                "list",
                "--pack-dir",
                str(root),
            ],
            stream=output,
        )

        if (
            customer_rc != 0
            or supplier_rc != 0
            or customer_list_rc != 0
            or supplier_list_rc != 0
        ):
            failures.append("guided CLI command contract failed")

        output_text = output.getvalue()
        if (
            '"customer_name": "CLI Customer"' not in output_text
            or '"supplier_name": "CLI Supplier"' not in output_text
            or "ops@cli-customer.invalid" in output_text
            or "rfq@cli-supplier.invalid" in output_text
        ):
            failures.append(
                "guided CLI summary output is unsafe or incomplete"
            )

    with tempfile.TemporaryDirectory() as max_temporary:
        root = Path(max_temporary) / "pilot-pack"
        paths = initialize_pack(root)
        for index in range(3):
            _add_customer(
                paths,
                f"Max Customer {index + 1}",
                f"ops-{index + 1}@max-customer-{index + 1}.invalid",
            )
        before = paths.customer_memory.read_bytes()
        try:
            _add_customer(
                paths,
                "Too Many Customers",
                "ops-4@max-customer-4.invalid",
            )
        except PilotDataPackIntakeError:
            pass
        else:
            failures.append(
                "guided intake exceeded active customer maximum"
            )
        if paths.customer_memory.read_bytes() != before:
            failures.append(
                "rejected maximum-cardinality intake changed data"
            )

    return {
        "name": "Guided pilot data-pack intake",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    print(evaluate_pilot_data_pack_intake_regressions())
