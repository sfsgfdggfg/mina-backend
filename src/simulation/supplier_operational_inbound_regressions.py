from __future__ import annotations

from datetime import datetime, timezone

from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundMailEnvelope
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.supplier_operational_inbound import (
    InMemorySupplierOperationalNotificationRepository,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail


def evaluate_supplier_operational_inbound_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str):
        (passes if condition else failures).append(label)

    master = InMemoryMasterDataRepository()
    create_supplier_master(
        repository=master,
        entry_id="nmt",
        supplier_name="NMT Lojistik",
        updated_by="regression",
        trusted_sender_domains=["nmtgrup.com"],
    )
    notifications = InMemorySupplierOperationalNotificationRepository()

    def forbidden_parser(*args, **kwargs):
        raise AssertionError("operational supplier mail must not call AI parser")

    def route(mail):
        return process_controlled_outlook_inbound_mail(
            mail=mail,
            shipment_parser=forbidden_parser,
            supplier_parser=forbidden_parser,
            proposal_repository=InMemoryExtractionProposalRepository(),
            supplier_repository=InMemorySupplierRFQRepository(),
            operational_data_sources=None,
            master_data_repository=master,
            supplier_operational_repository=notifications,
        )

    common = {
        "provider_name": "microsoft_graph",
        "mailbox_id": "info@luvilog.com",
        "received_at": datetime(2026, 9, 24, 8, 38, tzinfo=timezone.utc),
        "source": "email",
    }
    sea = InboundMailEnvelope(
        external_message_id="sea-1",
        sender_address="noreply@nmtgrup.com",
        subject="NAV - Navlun Sözleşmesi ve Çıkış İhbarı / SEA FCL / SMER00051022",
        body_text="2 x 40HC konteyner. Valencia Mersin. ETD 21.09 ETA 02.10. Konşimento.",
        **common,
    )
    road = InboundMailEnvelope(
        external_message_id="road-1",
        sender_address="ops@nmtgrup.com",
        subject="Araç yüklendi - Almanya",
        body_text="Plaka 34 ABC 123. Sürücü Ahmet. Kapıkule sınır kapısında. CMR hazır.",
        **common,
    )

    sea_first = route(sea)
    sea_duplicate = route(sea)
    road_result = route(road)

    check(
        sea_first.get("result_type") == "supplier_operational_notification"
        and sea_first.get("inbound_route") == "supplier_operation"
        and sea_first.get("transport_mode") == "sea"
        and "departure_notice" in sea_first.get("operational_event_types", []),
        "trusted sea supplier operation is separated from RFQ/customer intake",
    )
    check(
        road_result.get("result_type") == "supplier_operational_notification"
        and road_result.get("transport_mode") == "road"
        and "vehicle_assignment" in road_result.get("operational_event_types", [])
        and "tracking_update" in road_result.get("operational_event_types", []),
        "trusted road supplier operation uses the same transport-agnostic route",
    )
    check(
        sea_first.get("notification_id") == sea_duplicate.get("notification_id")
        and len(notifications.list_all()) == 2,
        "supplier operational queue is idempotent by provider mailbox message identity",
    )

    return {
        "name": "Supplier operational inbound routing",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_supplier_operational_inbound_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for failure in result["failures"]:
        print(f"FAIL {failure}")
    print(
        "\nSupplier operational inbound regressions:",
        "PASS" if result["passed"] else "FAIL",
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
