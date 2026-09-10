from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from src.core.agency_branding import AgencyBrandingSettings
from src.core.agency_branding_repository import SQLiteAgencyBrandingRepository
from src.core.attachment_interpretation_review import AttachmentInterpretationReview, AttachmentReviewEvidence
from src.core.attachment_interpretation_review_service import supplier_rfq_review_snapshot_sha256
from src.core.automation_policy import AgencyAutomationPolicy
from src.core.automation_policy_repository import SQLiteAgencyAutomationPolicyRepository
from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import SQLiteLearningFactRepository
from src.core.master_data import (
    CustomerMasterProfile,
    MasterContact,
    SupplierGeographyCapability,
    SupplierMasterProfile,
    SupplierRelationshipSettings,
)
from src.core.master_data_repository import SQLiteMasterDataRepository
from src.core.mina_job import MinaJobEvent
from src.core.mina_job_service import create_manual_mina_job
from src.core.models import CustomerQuote, Package, QuoteDraft, Shipment, SupplierQuote
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.mail import InboundAttachmentMetadata, InboundMailEnvelope
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.core.operation_execution import OperationException, OperationExecutionSnapshot
from src.core.operation_execution_repository import SQLiteOperationExecutionRepository
from src.core.operational_shift_close_receipt import OperationalShiftCloseReceipt
from src.core.operational_shift_open_acceptance_receipt import OperationalShiftOpenAcceptanceReceipt
from src.core.operational_work_assignment import OperationalWorkAssignment
from src.core.operational_work_assignment_service import work_state_fingerprint
from src.core.operational_work_queue import build_operational_work_queue
from src.core.performance_settings import PerformanceSettings
from src.core.performance_settings_repository import SQLitePerformanceSettingsRepository
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_case import CustomerQuoteManualSentEvidence, QuoteCase
from src.core.sqlite_repositories import (
    SQLiteMinaJobRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
    SQLiteOperationalWorkAssignmentRepository,
    SQLiteAttachmentInterpretationReviewRepository,
    SQLiteExtractionProposalRepository,
    SQLiteOperationalShiftCloseReceiptRepository,
    SQLiteOperationalShiftOpenAcceptanceReceiptRepository,
)
from src.core.supplier_price import SupplierFixedRate, SupplierPriceOffer, offer_from_rfq_response
from src.core.supplier_price_repository import SQLiteSupplierPriceRepository
from src.core.supplier_quote_selection import (
    RejectedSupplierQuoteAlternative,
    SupplierQuoteSelectionDecision,
)
from src.core.supplier_rfq import (
    SupplierRFQAcknowledgementEvidence,
    SupplierRFQAutomatedSentEvidence,
    SupplierRFQDraft,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")
DEMO_OPERATOR = "Demo Operator"
DEMO_SEED_VERSION = 5




def seed_demo_customer_memory(path: Path, *, reset: bool = False) -> dict:
    path = Path(path).expanduser().resolve()
    if path.exists() and not reset:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            return {"seeded": False, "profile_count": len(existing), "path": str(path)}
        except Exception:
            pass
    now = _utc_now().isoformat()
    profiles = [
        {"customer_name":"Atlas Tekstil","active":True,"aliases":["atlas","atlas textile"],"trusted_sender_addresses":["atlas@atlas-tekstil.customer.invalid"],"trusted_sender_domains":["atlas-tekstil.customer.invalid"],"default_commodity":"Tekstil","default_equipment_type":"Tenteli / Curtainsider","price_sensitivity":"high","time_sensitivity":"medium","pricing_policy":{"method":"cost_markup_percentage","value":12.0},"default_pickup_city":"Adana","default_pickup_area":"Hacı Sabancı OSB","default_pickup_country":"Türkiye","default_delivery_city":"Hamburg","default_delivery_country":"Almanya","created_at":now,"last_updated_at":now,"last_updated_by":"MINAI Demo Seeder","change_note":"Synthetic demo customer memory.","operational_notes":["Standart tekstil FTL taleplerinde bilinen adres ve ekipman varsayımları kullanılabilir."]},
        {"customer_name":"Mavi Makina","active":True,"aliases":["mavi machine"],"trusted_sender_addresses":["lojistik@mavi-makina.customer.invalid"],"trusted_sender_domains":["mavi-makina.customer.invalid"],"default_commodity":"Makina","default_equipment_type":"Tenteli / Curtainsider","price_sensitivity":"medium","time_sensitivity":"medium","pricing_policy":{"method":"cost_markup_percentage","value":15.0},"default_pickup_city":"Bursa","default_pickup_country":"Türkiye","default_delivery_city":"Stuttgart","default_delivery_country":"Almanya","created_at":now,"last_updated_at":now,"last_updated_by":"MINAI Demo Seeder","change_note":"Synthetic demo customer memory.","operational_notes":["Makina taleplerinde ölçü ve net ağırlık doğrulanmadan fiyatlama tamamlanmaz."]},
        {"customer_name":"Nova Gıda","active":True,"aliases":["nova food"],"trusted_sender_addresses":["export@nova-gida.customer.invalid"],"trusted_sender_domains":["nova-gida.customer.invalid"],"default_commodity":"Gıda","default_equipment_type":"Reefer","price_sensitivity":"medium","time_sensitivity":"high","pricing_policy":{"method":"cost_markup_percentage","value":14.0},"default_pickup_city":"Mersin","default_pickup_country":"Türkiye","default_delivery_city":"Münih","default_delivery_country":"Almanya","created_at":now,"last_updated_at":now,"last_updated_by":"MINAI Demo Seeder","change_note":"Synthetic demo customer memory.","operational_notes":["Isı kontrollü taleplerde sıcaklık gereksinimi müşteri mailinden ayrıca doğrulanır."]},
        {"customer_name":"Delta Elektrik","active":False,"aliases":["delta electric"],"trusted_sender_addresses":["ops@delta-elektrik.customer.invalid"],"trusted_sender_domains":["delta-elektrik.customer.invalid"],"default_commodity":"Elektrik ekipmanı","default_equipment_type":"Tenteli / Curtainsider","price_sensitivity":"high","time_sensitivity":"high","pricing_policy":None,"default_pickup_city":"Adana","default_pickup_country":"Türkiye","default_delivery_city":"Nürnberg","default_delivery_country":"Almanya","created_at":now,"last_updated_at":now,"last_updated_by":"MINAI Demo Seeder","change_note":"Synthetic inactive profile for status demo.","operational_notes":["Demo pasif profil örneği."]}
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"seeded": True, "profile_count": len(profiles), "path": str(path)}

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _today_istanbul(now: datetime) -> datetime:
    local = now.astimezone(ISTANBUL)
    return local.replace(hour=9, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _shipment(
    customer: str,
    pickup: str,
    delivery: str,
    *,
    commodity: str,
    weight_kg: float | None = None,
    equipment: str = "Tenteli",
    deadline: datetime | None = None,
    ready: str | None = None,
    delivery_date: str | None = None,
    temperature: str | None = None,
    adr_class: str | None = None,
    notes: str | None = None,
) -> Shipment:
    return Shipment(
        customer_name=customer,
        pickup_country="Türkiye",
        pickup_city=pickup,
        delivery_country={
            "Hamburg": "Germany", "Nürnberg": "Germany", "Stuttgart": "Germany",
            "Münih": "Germany", "Berlin": "Germany", "Frankfurt": "Germany",
            "Milano": "Italy", "Paris": "France", "Viyana": "Austria",
            "Prag": "Czechia", "Brno": "Czechia", "Utrecht": "Netherlands",
        }.get(delivery, "Germany"),
        delivery_city=delivery,
        commodity=commodity,
        gross_weight_kg=weight_kg,
        transport_mode="road",
        service_type="FTL",
        equipment_type=equipment,
        customer_quote_deadline_at=deadline,
        cargo_ready_date=ready,
        required_delivery_date=delivery_date,
        is_temperature_controlled=temperature is not None,
        temperature_requirement=temperature,
        is_adr=adr_class is not None,
        adr_class=adr_class,
        special_notes=notes,
    )


def _set_job_state(repo: SQLiteMinaJobRepository, job, *, stage: str, when: datetime, workflow_id=None, quote_case_id=None):
    terminal = stage in {"completed", "lost", "cancelled"}
    updated = job.model_copy(update={
        "stage": stage,
        "supplier_rfq_workflow_id": workflow_id if workflow_id is not None else job.supplier_rfq_workflow_id,
        "quote_case_id": quote_case_id if quote_case_id is not None else job.quote_case_id,
        "updated_at": when,
        "closed_at": when if terminal else None,
    })
    repo.save(updated)
    repo.append_event(MinaJobEvent(
        job_id=updated.job_id,
        mina_code=updated.mina_code,
        event_type="demo_stage_seeded",
        occurred_at=when,
        actor="MINAI Demo Seeder",
        metadata={"to_stage": stage, "synthetic": True},
    ))
    return updated


def _create_job(repo: SQLiteMinaJobRepository, *, index: int, shipment: Shipment, opened_at: datetime, stage: str, kind: str = "price_request", sales="Demo Sales", ops="Demo Ops"):
    job = create_manual_mina_job(
        repository=repo,
        manual_intake_id=f"demo-seed-{index}",
        intake_channel="email",
        job_kind=kind,
        shipment=shipment,
        opened_by=DEMO_OPERATOR,
        opened_at=opened_at,
        sales_owner=sales,
        operations_owner=ops,
    )
    return _set_job_state(repo, job, stage=stage, when=opened_at + timedelta(minutes=15))


def _seed_master_data(store: SQLitePilotStore, now: datetime):
    repo = SQLiteMasterDataRepository(store)
    customer_names = [
        "Atlas Tekstil", "Mavi Makina", "Nova Gıda", "Orion Kimya", "Polar Gıda",
        "Delta Elektrik", "Artemis Seramik", "Solena Kozmetik", "Mira Medikal",
        "Astra Kablo", "Kora Ev Tekstili", "Lale Mobilya",
    ]
    customers = {}
    for name in customer_names:
        slug = name.casefold().replace(" ", "-").replace("ı", "i").replace("ü", "u").replace("ş", "s").replace("ğ", "g").replace("ç", "c").replace("ö", "o")
        profile = CustomerMasterProfile(
            entry_id=f"demo-customer-{slug}",
            customer_name=name,
            trusted_sender_addresses=[f"ops@{slug}.customer.invalid"],
            contacts=[MasterContact(
                contact_name=f"{name} Operasyon",
                email=f"ops@{slug}.customer.invalid",
                roles=["operations"],
                is_primary=True,
            )],
            default_pickup_country="Türkiye",
            sales_owner="Demo Sales",
            time_sensitivity="high" if name in {"Delta Elektrik", "Mira Medikal"} else "normal",
            operational_notes=["Tamamen sentetik demo müşteri profili."],
            created_at=now,
            updated_at=now,
            updated_by="MINAI Demo Seeder",
        )
        stored, _ = repo.create_customer(profile)
        customers[name] = stored

    supplier_specs = [
        ("Rhein Cargo", "primary", 0.92, 0.76, 0.90, "Germany", "main_market", 30, 120, ["İlk fiyatı çoğu zaman pazarlığa açıktır."]),
        ("Anatolia Transport", "primary", 0.84, 0.90, 0.72, "Germany", "strong", 30, 120, ["Fiyat rekabetçi; yoğun günlerde cevap gecikebilir."]),
        ("NordLine Logistics", "backup", 0.78, 0.82, 0.68, "Germany", "works", 45, 120, ["E-posta sessizliğinde telefon takibi daha etkili olabilir."]),
        ("EuroHaul", "primary", 0.88, 0.73, 0.85, "Italy", "strong", 30, 90, ["İtalya hattında düzenli çalışır."]),
        ("FrigoTrans", "specialist", 0.95, 0.68, 0.88, "Germany", "strong", 30, 120, ["Reefer ve sıcaklık kontrollü yüklerde öncelikli uzman."]),
        ("MedRoad", "specialist", 0.91, 0.70, 0.86, "Germany", "strong", 30, 120, ["Medikal yüklerde operasyon teyidi dikkatle alınır."]),
    ]
    suppliers = {}
    for name, role, reliability, price, speed, country, strength, first_reminder, ack_wait, notes in supplier_specs:
        slug = name.casefold().replace(" ", "-")
        profile = SupplierMasterProfile(
            entry_id=f"demo-supplier-{slug}",
            supplier_name=name,
            role=role,
            contacts=[MasterContact(
                contact_name=f"{name} Fiyatlama",
                email=f"pricing@{slug}.supplier.invalid",
                phone="+90 555 000 00 00",
                roles=["pricing", "operations"],
                is_primary=True,
            )],
            geographies=[SupplierGeographyCapability(
                scope_type="country", scope_name=country, strength=strength,
                source="manual", notes="Sentetik demo coğrafya kabiliyeti.",
            )],
            service_types=["FTL"],
            equipment_types=["Tenteli", "Reefer", "Mega"],
            reliability_score=reliability,
            price_score=price,
            speed_score=speed,
            relationship=SupplierRelationshipSettings(
                preferred_contact_channels=["email", "phone", "whatsapp"],
                preferred_language="Turkish",
                supplier_reminder_mode="approval_required",
                first_reminder_minutes=first_reminder,
                acknowledged_wait_minutes=ack_wait,
                max_email_reminders=1,
                phone_escalation_after_minutes=60,
                whatsapp_escalation_after_minutes=60,
                management_escalation_allowed=True,
                operation_email_mode="approval_required",
                closure_email_mode="approval_required",
                negotiation_notes=notes,
                relationship_notes=["Sentetik demo ilişki profili."],
            ),
            notes="Synthetic MINAI Demo Agency supplier.",
            created_at=now,
            updated_at=now,
            updated_by="MINAI Demo Seeder",
        )
        stored, _ = repo.create_supplier(profile)
        suppliers[name] = stored
    return customers, suppliers


def _seed_workflow(
    *,
    rfq_repo: SQLiteSupplierRFQRepository,
    price_repo: SQLiteSupplierPriceRepository,
    job_repo: SQLiteMinaJobRepository,
    job,
    specs: list[dict],
    now: datetime,
):
    workflow = SupplierRFQWorkflow(
        shipment=job.shipment,
        mina_job_id=job.job_id,
        mina_code=job.mina_code,
        sender_address=f"ops@{job.shipment.customer_name.casefold().replace(' ', '-')}.customer.invalid",
        customer_subject=f"{job.shipment.pickup_city} - {job.shipment.delivery_city} taşıma talebi",
        automation_timing_version=1,
        created_at=now - timedelta(hours=2),
        updated_at=now,
    )
    drafts = []
    responses = []
    for idx, spec in enumerate(specs, start=1):
        supplier = spec["name"]
        slug = supplier.casefold().replace(" ", "-")
        rfq_id = f"demo-{job.sequence_number}-rfq-{idx}"
        status = spec.get("draft_status", "awaiting_response")
        sent_at = spec.get("sent_at", now - timedelta(minutes=spec.get("sent_minutes_ago", 45)))
        draft = SupplierRFQDraft(
            rfq_id=rfq_id,
            workflow_id=workflow.workflow_id,
            supplier_name=supplier,
            priority=idx,
            recipient_email=f"pricing@{slug}.supplier.invalid",
            supplier_role=spec.get("role", "primary"),
            dispatch_tier=spec.get("tier", "primary"),
            subject=f"{job.mina_code} - {job.shipment.pickup_city} → {job.shipment.delivery_city} RFQ",
            body="Synthetic demo RFQ. Gerçek bir gönderi değildir.",
            status=status,
            approved_by=DEMO_OPERATOR if status in {"approved", "sent", "awaiting_response", "responded"} else None,
            approved_at=(sent_at - timedelta(minutes=2)) if status in {"approved", "sent", "awaiting_response", "responded"} else None,
            sent_at=sent_at if status in {"sent", "awaiting_response", "responded"} else None,
            responded_at=(now - timedelta(minutes=spec.get("response_minutes_ago", 10))) if spec.get("response") else None,
            created_at=now - timedelta(hours=2),
        )
        drafts.append(draft)
        if spec.get("sent_evidence") and draft.sent_at is not None:
            rfq_repo.save_automated_sent_evidence(SupplierRFQAutomatedSentEvidence(
                rfq_id=rfq_id,
                recipient_email=draft.recipient_email,
                provider_name="minai_demo_outbox",
                provider_message_id=f"seed-msg-{rfq_id}",
                sent_at=draft.sent_at,
                triggered_by="MINAI Demo Seeder",
            ))
        if spec.get("ack"):
            rfq_repo.save_acknowledgement(SupplierRFQAcknowledgementEvidence(
                rfq_id=rfq_id,
                acknowledged_at=now - timedelta(minutes=spec.get("ack_minutes_ago", 20)),
                channel="email",
                recorded_by=DEMO_OPERATOR,
            ))
        response = spec.get("response")
        if response:
            response_obj = SupplierRFQResponse(
                rfq_id=rfq_id,
                supplier_name=supplier,
                rfq_priority=idx,
                status=response["status"],
                cost=response.get("cost"),
                currency=response.get("currency"),
                transit_time=response.get("transit_time"),
                equipment_type=response.get("equipment", job.shipment.equipment_type),
                source="email",
                received_at=draft.responded_at or now,
            )
            responses.append(response_obj)
    workflow = workflow.model_copy(update={"rfq_ids": [item.rfq_id for item in drafts]})
    rfq_repo.save_workflow(workflow)
    rfq_repo.save_drafts(drafts)
    if responses:
        rfq_repo.save_responses(responses)
        for response in responses:
            if response.is_price_usable:
                price_repo.create_offer(offer_from_rfq_response(
                    response=response,
                    job_id=job.job_id,
                    mina_code=job.mina_code,
                ))
    job = _set_job_state(
        job_repo, job, stage=job.stage, when=now,
        workflow_id=workflow.workflow_id,
    )
    return job, workflow, drafts, responses


def _seed_quote(
    *,
    quote_repo: SQLiteQuoteCaseRepository,
    approval_repo: SQLiteQuoteApprovalRepository,
    job_repo: SQLiteMinaJobRepository,
    job,
    supplier_name: str,
    supplier_cost: float,
    final_price: float,
    currency: str = "EUR",
    approval_status: str = "pending",
    selected_rfq_id: str | None = None,
    alternatives: list[RejectedSupplierQuoteAlternative] | None = None,
    sent: bool = False,
    now: datetime,
):
    supplier_quote = SupplierQuote(
        supplier_name=supplier_name,
        cost=supplier_cost,
        currency=currency,
        transit_time="5-7 gün",
        equipment_type=job.shipment.equipment_type,
        pricing_basis="all_in",
    )
    customer_quote = CustomerQuote(
        supplier_cost=supplier_cost,
        markup_type="fixed_profit",
        markup_value=final_price - supplier_cost,
        final_price=final_price,
        currency=currency,
    )
    quote_draft = QuoteDraft(
        subject=f"{job.mina_code} - Taşıma teklifimiz",
        body=(
            f"Merhaba,\n\n{job.shipment.pickup_city} → {job.shipment.delivery_city} taşımanız için "
            f"fiyatımız {final_price:.0f} {currency}'dur.\n\nBu metin MINAI demo verisidir."
        ),
    )
    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )
    if approval_status == "approved":
        approval = QuoteApproval(
            approval_status="approved",
            approved_by=DEMO_OPERATOR,
            approved_at=now - timedelta(minutes=20),
            quote_snapshot=snapshot,
            created_at=now - timedelta(minutes=30),
        )
    else:
        approval = QuoteApproval(
            approval_status="pending",
            quote_snapshot=snapshot,
            created_at=now - timedelta(minutes=30),
        )
    approval_repo.save(approval)
    selection = None
    if selected_rfq_id:
        selection = SupplierQuoteSelectionDecision(
            selected_supplier=supplier_name,
            selected_rfq_id=selected_rfq_id,
            selected_total_score=0.91,
            selection_reason="Demo seçim motoru: fiyat, güvenilirlik ve hız birlikte değerlendirildi.",
            rejected_alternatives=alternatives or [],
        )
    case = QuoteCase(
        shipment=job.shipment,
        mina_job_id=job.job_id,
        mina_code=job.mina_code,
        supplier_rfq_workflow_id=job.supplier_rfq_workflow_id,
        supplier_quote_selection_decision=selection,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        quote_approval=approval,
        created_at=now - timedelta(minutes=30),
        updated_at=now,
    )
    if sent:
        customer_slug = job.shipment.customer_name.casefold().replace(" ", "-")
        case.manual_sent_evidence.append(CustomerQuoteManualSentEvidence(
            case_id=case.case_id,
            approval_id=approval.approval_id,
            revision_number=0,
            recipient_email=f"ops@{customer_slug}.customer.invalid",
            sent_by=DEMO_OPERATOR,
            sent_at=now - timedelta(minutes=5),
        ))
    quote_repo.save(case)
    job = _set_job_state(job_repo, job, stage=job.stage, when=now, quote_case_id=case.case_id)
    return job, case, approval


def _seed_attachment_reviews(store: SQLitePilotStore, now: datetime) -> int:
    reviews = SQLiteAttachmentInterpretationReviewRepository(store)
    rfqs = SQLiteSupplierRFQRepository(store)

    customer_mail_body = "Ekli yük listesinde Bursa-Stuttgart makina sevkiyat detayları bulunmaktadır."
    customer_mail_hash = hashlib.sha256(customer_mail_body.encode("utf-8")).hexdigest()
    customer_review = AttachmentInterpretationReview(
        review_id="demo-attachment-review-customer", route="customer",
        source_message_key="demo-attachment-message-customer",
        source_fingerprint_sha256=hashlib.sha256(b"demo-customer-attachment").hexdigest(),
        inbound_mail=InboundMailEnvelope(
            external_message_id="demo-attachment-customer-001", provider_name="synthetic_demo_mailbox",
            mailbox_id="demo", sender_address="lojistik@mavi-makina.customer.invalid", sender_name="Mavi Makina",
            recipient_addresses=["ops@minai.invalid"], subject="Bursa Stuttgart makina yük listesi",
            body_text=customer_mail_body, raw_body_sha256=customer_mail_hash, privacy_transformed=True,
            privacy_transform_version="demo-synthetic-v1", received_at=now - timedelta(minutes=22),
            has_attachments=True, attachment_manifest=[InboundAttachmentMetadata(
                name="yuk-listesi.xlsx", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                size_bytes=18432, kind="file",
            )], source="email",
        ),
        attachment_evidence=[AttachmentReviewEvidence(
            content_profile="xlsx", size_bytes=18432,
            sha256_hex=hashlib.sha256(b"demo-xlsx-bytes").hexdigest(),
        )],
        privacy_transform_version="demo-synthetic-v1", source_character_count=428, source_table_count=1,
        trusted_customer_name="Mavi Makina", customer_candidate=ShipmentProposalSnapshot(
            customer_name="Mavi Makina", pickup_country="Türkiye", pickup_city="Bursa",
            delivery_country="Germany", delivery_city="Stuttgart", delivery_postcode="70173",
            commodity="Makina", gross_weight_kg=3200, weight_is_approximate=False, service_type="FTL",
            transport_mode="road", equipment_type="Tenteli", cargo_ready_date="2026-09-12",
            is_adr=False, is_temperature_controlled=False, is_high_value=None,
            packages=[Package(package_type="kasa", quantity=1, length_cm=320, width_cm=190, height_cm=280, weight_kg=3200)],
        ), created_at=now - timedelta(minutes=20),
    )
    reviews.save(customer_review)

    draft = next((item for item in rfqs.list_drafts() if item.status == "awaiting_response" and item.recipient_email and not rfqs.list_responses(item.rfq_id)), None)
    if draft is not None:
        supplier_body = "Teklifimiz ekli PDF'dedir. All-in 2470 EUR, transit 5 gün."
        supplier_hash = hashlib.sha256(supplier_body.encode("utf-8")).hexdigest()
        supplier_review = AttachmentInterpretationReview(
            review_id="demo-attachment-review-supplier", route="supplier",
            source_message_key="demo-attachment-message-supplier",
            source_fingerprint_sha256=hashlib.sha256(b"demo-supplier-attachment").hexdigest(),
            inbound_mail=InboundMailEnvelope(
                external_message_id="demo-attachment-supplier-001", provider_name="synthetic_demo_mailbox", mailbox_id="demo",
                sender_address=draft.recipient_email, sender_name=draft.supplier_name, recipient_addresses=["ops@minai.invalid"],
                subject=f"Re: {draft.subject}", body_text=supplier_body, raw_body_sha256=supplier_hash,
                privacy_transformed=True, privacy_transform_version="demo-synthetic-v1", received_at=now - timedelta(minutes=15),
                explicit_rfq_reference=draft.rfq_id, has_attachments=True, attachment_manifest=[InboundAttachmentMetadata(
                    name="teklif.pdf", content_type="application/pdf", size_bytes=56320, kind="file",
                )], source="email",
            ),
            attachment_evidence=[AttachmentReviewEvidence(
                content_profile="pdf", size_bytes=56320, sha256_hex=hashlib.sha256(b"demo-pdf-bytes").hexdigest(),
            )], privacy_transform_version="demo-synthetic-v1", source_character_count=186, source_table_count=1,
            rfq_id=draft.rfq_id, correlation_method="explicit_demo_rfq",
            expected_rfq_snapshot_sha256=supplier_rfq_review_snapshot_sha256(draft),
            supplier_candidate=SupplierResponseExtraction(
                status="quoted", cost=2470.0, currency="EUR", transit_time=None, equipment_type="Tenteli",
                pricing_basis="all_in", uncertain_fields=["transit_time"],
            ), created_at=now - timedelta(minutes=14),
        )
        reviews.save(supplier_review)
    return len(reviews.list_all())


def _seed_shift_continuity(store: SQLitePilotStore, now: datetime) -> int:
    closes = SQLiteOperationalShiftCloseReceiptRepository(store)
    opens = SQLiteOperationalShiftOpenAcceptanceReceiptRepository(store)
    close_id = "shift-close-" + hashlib.sha256(b"demo-historical-close").hexdigest()[:32]
    open_id = "shift-open-" + hashlib.sha256(b"demo-historical-open").hexdigest()[:32]
    close_at = now - timedelta(hours=18)
    open_at = now - timedelta(hours=4)
    closes.save_if_absent(OperationalShiftCloseReceipt(
        receipt_id=close_id, attested_by="Ayşe Demo", attested_at=close_at,
        readiness_generated_at=close_at - timedelta(minutes=2), pending_work_count=5,
        critical_pending_count=1, active_assignment_count=0, expired_assignment_count=0,
        incomplete_handoff_count=0, critical_uncovered_count=0,
        close_state_sha256=hashlib.sha256(b"demo-historical-close-state").hexdigest(),
        state_event_id=0,
    ))
    opens.save_if_absent(OperationalShiftOpenAcceptanceReceipt(
        receipt_id=open_id, accepted_by="Mehmet Demo", accepted_at=open_at,
        reconciliation_generated_at=open_at - timedelta(minutes=1), source_close_receipt_id=close_id,
        pending_work_count=6, critical_pending_count=1, incomplete_handoff_count=0,
        critical_uncovered_count=0,
        acceptance_state_sha256=hashlib.sha256(b"demo-historical-open-state").hexdigest(),
    ))
    return len(closes.list_all()) + len(opens.list_all())


def _seed_operational_assignments(store: SQLitePilotStore, now: datetime) -> int:
    assignments = SQLiteOperationalWorkAssignmentRepository(store)
    attachments = SQLiteAttachmentInterpretationReviewRepository(store)
    proposals = SQLiteExtractionProposalRepository(store)
    suppliers = SQLiteSupplierRFQRepository(store)
    approvals = SQLiteQuoteApprovalRepository(store)
    quotes = SQLiteQuoteCaseRepository(store)
    queue = build_operational_work_queue(
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=quotes,
        now=now,
    )
    items = list(queue.get("items", []))
    if not items:
        return 0

    def assigned(item, operator: str, *, minutes_ago: int, generation: int = 1,
                 assigned_by: str = "MINAI Demo Seeder", reassigned_from: str | None = None):
        at = now - timedelta(minutes=minutes_ago)
        return OperationalWorkAssignment(
            work_id=item["work_id"], assigned_to=operator, assigned_by=assigned_by,
            reassigned_from=reassigned_from, assignment_reason="Sentetik demo iş dağılımı",
            status="assigned", assigned_at=at, last_renewed_at=at,
            lease_expires_at=at + timedelta(minutes=30), generation=generation,
            work_state_sha256=work_state_fingerprint(item),
        )

    # Active assignment with first-look evidence.
    first = assigned(items[0], "Demo Operator", minutes_ago=10)
    assignments.save(first)
    assignments.save(first.model_copy(update={
        "status": "acknowledged",
        "acknowledged_at": now - timedelta(minutes=4),
        "last_renewed_at": now - timedelta(minutes=4),
        "lease_expires_at": now + timedelta(minutes=26),
    }))

    if len(items) > 1:
        second = assigned(items[1], "Ayşe Demo", minutes_ago=14)
        assignments.save(second)
        assignments.save(second.model_copy(update={
            "status": "acknowledged",
            "acknowledged_at": now - timedelta(minutes=6),
            "last_renewed_at": now - timedelta(minutes=6),
            "lease_expires_at": now + timedelta(minutes=24),
        }))

    if len(items) > 2:
        # Preserve one explicit shift handoff and a second assignment generation.
        third = assigned(items[2], "Mehmet Demo", minutes_ago=25)
        assignments.save(third)
        third_ack = third.model_copy(update={
            "status": "acknowledged",
            "acknowledged_at": now - timedelta(minutes=20),
            "last_renewed_at": now - timedelta(minutes=20),
            "lease_expires_at": now + timedelta(minutes=10),
        })
        assignments.save(third_ack)
        assignments.save(third_ack.model_copy(update={
            "status": "released",
            "released_at": now - timedelta(minutes=12),
            "released_by": "Mehmet Demo",
            "release_reason": "shift_handoff",
        }))
        reassigned = assigned(
            items[2], "Demo Operator", minutes_ago=8, generation=2,
            reassigned_from="Mehmet Demo",
        )
        assignments.save(reassigned)
        assignments.save(reassigned.model_copy(update={
            "status": "acknowledged",
            "acknowledged_at": now - timedelta(minutes=3),
            "last_renewed_at": now - timedelta(minutes=3),
            "lease_expires_at": now + timedelta(minutes=27),
        }))

    if len(items) > 3:
        # Intentionally expired assignment keeps takeover/recovery visible in the queue.
        assignments.save(assigned(items[3], "Ayşe Demo", minutes_ago=45))

    return min(4, len(items))


def _seed_fixed_rates(price_repo: SQLiteSupplierPriceRepository, now: datetime) -> int:
    today = now.astimezone(ISTANBUL).date()
    rates = [
        SupplierFixedRate(entry_id="demo-fixed-de-ftl", supplier_name="Rhein Cargo", origin_country="Türkiye", destination_country="Germany", transport_mode="road", service_type="FTL", equipment_type="Tenteli", cost=2380, currency="EUR", transit_time="5-6 gün", pricing_basis="all_in", included_costs=[], excluded_costs=[], valid_from=today-timedelta(days=15), valid_to=today+timedelta(days=45), evidence_source="agreement", evidence_reference="DEMO-CONTRACT-DE-2026", recorded_by=DEMO_OPERATOR, notes="Sentetik Almanya FTL anlaşma fiyatı."),
        SupplierFixedRate(entry_id="demo-fixed-nl-ftl", supplier_name="NordLine Logistics", origin_country="Türkiye", destination_country="Netherlands", transport_mode="road", service_type="FTL", equipment_type="Tenteli", cost=2650, currency="EUR", transit_time="6-7 gün", pricing_basis="all_in", included_costs=[], excluded_costs=[], valid_from=today-timedelta(days=10), valid_to=today+timedelta(days=30), evidence_source="email", evidence_reference="DEMO-RATE-NL-0901", recorded_by=DEMO_OPERATOR, notes="Sentetik Hollanda FTL fiyatı."),
        SupplierFixedRate(entry_id="demo-fixed-de-reefer", supplier_name="FrigoTrans", origin_country="Türkiye", destination_country="Germany", transport_mode="road", service_type="FTL", equipment_type="Reefer", cost=3120, currency="EUR", transit_time="5-6 gün", pricing_basis="all_in", included_costs=[], excluded_costs=[], valid_from=today-timedelta(days=5), valid_to=today+timedelta(days=20), evidence_source="agreement", evidence_reference="DEMO-REEFER-DE-2026", recorded_by=DEMO_OPERATOR, notes="Sentetik +4/-18 reefer anlaşma fiyatı."),
    ]
    for rate in rates:
        price_repo.create_fixed_rate(rate)
    return len(price_repo.list_fixed_rates())


def seed_demo_database(db_path: str | Path, *, reset: bool = False) -> dict:
    db_path = Path(db_path).expanduser()
    if reset and db_path.exists():
        db_path.unlink()
    store = SQLitePilotStore(db_path, run_id="minai-demo-seed", retention_days=365)
    marker = store.get(namespace="demo_seed_metadata", record_key="current")
    if marker and marker.get("version") == DEMO_SEED_VERSION:
        return {"seeded": False, "reason": "already_seeded", "db_path": str(db_path)}

    now = _utc_now()
    day = _today_istanbul(now)
    job_repo = SQLiteMinaJobRepository(store)
    rfq_repo = SQLiteSupplierRFQRepository(store)
    price_repo = SQLiteSupplierPriceRepository(store)
    quote_repo = SQLiteQuoteCaseRepository(store)
    approval_repo = SQLiteQuoteApprovalRepository(store)
    operation_repo = SQLiteOperationExecutionRepository(store)
    learning_repo = SQLiteLearningFactRepository(store)

    customers, suppliers = _seed_master_data(store, now)
    fixed_rate_count = _seed_fixed_rates(price_repo, now)
    SQLiteAgencyBrandingRepository(store).save(AgencyBrandingSettings(
        company_name="MINAI Demo Agency",
        logo_data_uri=None,
        primary_color="#0F766E",
        secondary_accent_color="#172033",
        updated_at=now,
        updated_by="MINAI Demo Seeder",
    ))
    SQLiteAgencyAutomationPolicyRepository(store).save(AgencyAutomationPolicy(
        supplier_reminder_mode="approval_required",
        customer_deadline_update_mode="approval_required",
        updated_at=now,
        updated_by="MINAI Demo Seeder",
    ))
    SQLitePerformanceSettingsRepository(store).save(PerformanceSettings(
        first_look_target_minutes=15,
        decision_target_minutes=20,
        updated_at=now,
        updated_by="MINAI Demo Seeder",
    ))

    jobs = []

    # 1 — Active pricing with multiple supplier behaviours and customer deadline.
    j1 = _create_job(job_repo, index=1, opened_at=day - timedelta(hours=1), stage="pricing", shipment=_shipment(
        "Atlas Tekstil", "Adana", "Hamburg", commodity="Tekstil", weight_kg=20000,
        deadline=day + timedelta(hours=4), ready=(day + timedelta(days=1)).date().isoformat(),
        delivery_date=(day + timedelta(days=5)).date().isoformat(),
    ))
    j1, w1, d1, r1 = _seed_workflow(
        rfq_repo=rfq_repo, price_repo=price_repo, job_repo=job_repo, job=j1, now=now,
        specs=[
            {"name":"Rhein Cargo","sent_minutes_ago":55,"sent_evidence":True,"response":{"status":"quoted","cost":2420,"currency":"EUR","transit_time":"5 gün"}},
            {"name":"Anatolia Transport","sent_minutes_ago":55,"sent_evidence":True,"ack":True},
            {"name":"NordLine Logistics","role":"backup","tier":"secondary","draft_status":"draft","sent_at":now},
        ],
    )
    jobs.append(j1)

    # 2 — Missing-information style intake.
    j2 = _create_job(job_repo, index=2, opened_at=day - timedelta(minutes=35), stage="inquiry_confirmed", shipment=_shipment(
        "Mavi Makina", "Bursa", "Stuttgart", commodity="Makina", weight_kg=None,
        equipment="Tenteli", notes="Makina ölçüleri ve net ağırlık henüz eksik.",
    ))
    jobs.append(j2)

    # 3 — Accepted quote ready for Operasyonu Başlat.
    j3 = _create_job(job_repo, index=3, opened_at=day - timedelta(hours=3), stage="accepted", shipment=_shipment(
        "Nova Gıda", "Mersin", "Münih", commodity="Gıda", weight_kg=18000,
        equipment="Reefer", temperature="+4°C", ready=day.date().isoformat(),
        delivery_date=(day + timedelta(days=4)).date().isoformat(),
    ))
    j3, w3, d3, r3 = _seed_workflow(
        rfq_repo=rfq_repo, price_repo=price_repo, job_repo=job_repo, job=j3, now=now,
        specs=[
            {"name":"FrigoTrans","sent_minutes_ago":100,"sent_evidence":True,"response":{"status":"quoted","cost":2850,"currency":"EUR","transit_time":"4 gün","equipment":"Reefer"}},
            {"name":"Rhein Cargo","sent_minutes_ago":100,"sent_evidence":True,"response":{"status":"quoted","cost":2980,"currency":"EUR","transit_time":"5 gün","equipment":"Reefer"}},
        ],
    )
    alt = RejectedSupplierQuoteAlternative(
        rfq_id=d3[1].rfq_id,
        supplier_name="Rhein Cargo",
        cost=2980,
        currency="EUR",
        total_score=0.78,
        score_difference=0.13,
        price_difference=130,
        rejection_reason="Demo karşılaştırmasında toplam skor daha düşük.",
    )
    j3, c3, a3 = _seed_quote(
        quote_repo=quote_repo, approval_repo=approval_repo, job_repo=job_repo, job=j3,
        supplier_name="FrigoTrans", supplier_cost=2850, final_price=3150,
        approval_status="approved", selected_rfq_id=d3[0].rfq_id, alternatives=[alt], sent=True, now=now,
    )
    jobs.append(j3)

    # 4 — Pending approval / ADR review example.
    j4 = _create_job(job_repo, index=4, opened_at=day - timedelta(hours=2), stage="quote_ready", shipment=_shipment(
        "Orion Kimya", "İzmir", "Paris", commodity="Kimyasal", weight_kg=12000,
        equipment="ADR Tenteli", adr_class="3", deadline=day + timedelta(hours=2),
    ))
    j4, w4, d4, r4 = _seed_workflow(
        rfq_repo=rfq_repo, price_repo=price_repo, job_repo=job_repo, job=j4, now=now,
        specs=[{"name":"EuroHaul","sent_minutes_ago":80,"sent_evidence":True,"response":{"status":"quoted","cost":2670,"currency":"EUR","transit_time":"5 gün"}}],
    )
    j4, c4, a4 = _seed_quote(
        quote_repo=quote_repo, approval_repo=approval_repo, job_repo=job_repo, job=j4,
        supplier_name="EuroHaul", supplier_cost=2670, final_price=3020,
        approval_status="pending", selected_rfq_id=d4[0].rfq_id, now=now,
    )
    jobs.append(j4)

    # 5 — In transit with active exception.
    j5 = _create_job(job_repo, index=5, opened_at=day - timedelta(days=1), stage="in_transit", kind="approved_job", shipment=_shipment(
        "Polar Gıda", "Mersin", "Berlin", commodity="Dondurulmuş gıda", weight_kg=19500,
        equipment="Reefer", temperature="-18°C", delivery_date=(day + timedelta(days=2)).date().isoformat(),
    ))
    operation_repo.save_snapshot(OperationExecutionSnapshot(
        job_id=j5.job_id,
        mina_code=j5.mina_code,
        vehicle_plate="34 DEMO 501",
        driver_name="Demo Şoför 1",
        loading_appointment_at=day - timedelta(hours=6),
        vehicle_assigned_at=day - timedelta(hours=5),
        loaded_at=day - timedelta(hours=4),
        current_eta=day + timedelta(days=2, hours=7),
        delivery_appointment_at=day + timedelta(days=2, hours=8),
        updated_at=now,
        updated_by=DEMO_OPERATOR,
    ))
    operation_repo.create_exception(OperationException(
        entry_id="demo-exception-border",
        job_id=j5.job_id,
        mina_code=j5.mina_code,
        stage_at_report="in_transit",
        exception_type="border_congestion",
        impact_level="delivery_risk",
        cause="Sentetik sınır yoğunluğu senaryosu",
        source_type="operator",
        reported_at=now - timedelta(minutes=30),
        created_at=now - timedelta(minutes=30),
        created_by=DEMO_OPERATOR,
        updated_at=now - timedelta(minutes=30),
        updated_by=DEMO_OPERATOR,
    ))
    jobs.append(j5)

    # 6 — Overdue pricing attention.
    j6 = _create_job(job_repo, index=6, opened_at=day - timedelta(hours=5), stage="pricing", shipment=_shipment(
        "Delta Elektrik", "Adana", "Nürnberg", commodity="Elektrik ekipmanı", weight_kg=18500,
        deadline=day - timedelta(minutes=20), ready=(day + timedelta(days=1)).date().isoformat(),
    ))
    j6, w6, d6, r6 = _seed_workflow(
        rfq_repo=rfq_repo, price_repo=price_repo, job_repo=job_repo, job=j6, now=now,
        specs=[
            {"name":"Rhein Cargo","sent_minutes_ago":65,"sent_evidence":True},
            {"name":"Anatolia Transport","sent_minutes_ago":65,"sent_evidence":True},
        ],
    )
    jobs.append(j6)

    # 7 — Quote sent / negotiation example.
    j7 = _create_job(job_repo, index=7, opened_at=day - timedelta(hours=4), stage="negotiation", shipment=_shipment(
        "Artemis Seramik", "Kütahya", "Milano", commodity="Seramik", weight_kg=22000,
        ready=(day + timedelta(days=1)).date().isoformat(),
    ))
    j7, w7, d7, r7 = _seed_workflow(
        rfq_repo=rfq_repo, price_repo=price_repo, job_repo=job_repo, job=j7, now=now,
        specs=[{"name":"EuroHaul","sent_minutes_ago":90,"sent_evidence":True,"response":{"status":"quoted","cost":2620,"currency":"EUR","transit_time":"4 gün"}}],
    )
    j7, c7, a7 = _seed_quote(
        quote_repo=quote_repo, approval_repo=approval_repo, job_repo=job_repo, job=j7,
        supplier_name="EuroHaul", supplier_cost=2620, final_price=2890,
        approval_status="approved", selected_rfq_id=d7[0].rfq_id, sent=True, now=now,
    )
    jobs.append(j7)

    # 8 — Supplier escalation candidate.
    j8 = _create_job(job_repo, index=8, opened_at=day - timedelta(hours=2), stage="pricing", shipment=_shipment(
        "Solena Kozmetik", "İstanbul", "Paris", commodity="Kozmetik", weight_kg=9000,
        equipment="Kapalı Kasa", deadline=day + timedelta(hours=5),
    ))
    j8, w8, d8, r8 = _seed_workflow(
        rfq_repo=rfq_repo, price_repo=price_repo, job_repo=job_repo, job=j8, now=now,
        specs=[{"name":"NordLine Logistics","sent_minutes_ago":50,"sent_evidence":True}],
    )
    jobs.append(j8)

    # 9 — Friday/urgent approved operation stage.
    j9 = _create_job(job_repo, index=9, opened_at=day - timedelta(hours=1), stage="operation_opened", kind="approved_job", shipment=_shipment(
        "Mira Medikal", "İstanbul", "Frankfurt", commodity="Medikal cihaz", weight_kg=6500,
        equipment="Kapalı Kasa", ready=(day + timedelta(days=2)).date().isoformat(),
        notes="Acil / zaman hassas sentetik demo yükü.",
    ))
    jobs.append(j9)

    # 10 — Delivery / POD pending.
    j10 = _create_job(job_repo, index=10, opened_at=day - timedelta(days=3), stage="pod_cmr_pending", kind="approved_job", shipment=_shipment(
        "Kora Ev Tekstili", "Denizli", "Utrecht", commodity="Ev tekstili", weight_kg=17000,
        delivery_date=day.date().isoformat(),
    ))
    operation_repo.save_snapshot(OperationExecutionSnapshot(
        job_id=j10.job_id,
        mina_code=j10.mina_code,
        vehicle_plate="20 DEMO 610",
        driver_name="Demo Şoför 2",
        loaded_at=day - timedelta(days=3),
        delivered_at=day - timedelta(hours=1),
        updated_at=now,
        updated_by=DEMO_OPERATOR,
    ))
    jobs.append(j10)

    # 11 — Completed historical job to make reporting non-empty.
    j11 = _create_job(job_repo, index=11, opened_at=day - timedelta(days=8), stage="completed", kind="approved_job", shipment=_shipment(
        "Lale Mobilya", "Kayseri", "Hamburg", commodity="Mobilya", weight_kg=15500,
        delivery_date=(day - timedelta(days=2)).date().isoformat(),
    ))
    operation_repo.save_snapshot(OperationExecutionSnapshot(
        job_id=j11.job_id,
        mina_code=j11.mina_code,
        vehicle_plate="38 DEMO 711",
        driver_name="Demo Şoför 3",
        vehicle_assigned_at=day - timedelta(days=7),
        loaded_at=day - timedelta(days=7),
        delivered_at=day - timedelta(days=2),
        cmr_received_at=day - timedelta(days=1),
        updated_at=day - timedelta(days=1),
        updated_by=DEMO_OPERATOR,
    ))
    jobs.append(j11)

    # Supplier relationship memory facts (mix of confirmed and proposed).
    rhein = suppliers["Rhein Cargo"]
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference="demo-history-rhein-001",
        observed_at=now - timedelta(days=20),
        summary="Sentetik geçmiş RFQ örneklerinde ilk yanıt süresi düzenli olarak kısa gözlendi.",
    )
    learning_repo.create(LearningFact(
        entry_id="demo-learning-rhein-response",
        subject_type="supplier",
        subject_id=rhein.supplier_id,
        subject_label=rhein.supplier_name,
        fact_key="response.median_minutes",
        value=24,
        value_unit="minutes",
        confidence=0.91,
        source_type="minai_inference",
        evidence=[evidence],
        status="confirmed",
        created_at=now - timedelta(days=2),
        created_by="MINAI Demo Seeder",
        updated_at=now - timedelta(days=1),
        reviewed_at=now - timedelta(days=1),
        reviewed_by=DEMO_OPERATOR,
        review_note="Demo ortamında doğrulanmış örnek öğrenme kaydı.",
    ))
    learning_repo.create(LearningFact(
        entry_id="demo-learning-rhein-negotiation",
        subject_type="supplier",
        subject_id=rhein.supplier_id,
        subject_label=rhein.supplier_name,
        fact_key="commercial.negotiated_reduction_percent",
        value=6.4,
        value_unit="percent",
        confidence=0.78,
        source_type="minai_inference",
        evidence=[LearningEvidence(
            source_type="operation_history",
            source_reference="demo-history-rhein-002",
            observed_at=now - timedelta(days=10),
            summary="Sentetik teklif geçmişinde ilk fiyat ile kabul edilen fiyat arasında düşüş örüntüsü gözlendi.",
        )],
        created_at=now - timedelta(hours=6),
        created_by="MINAI Demo Seeder",
        updated_at=now - timedelta(hours=6),
    ))

    attachment_review_count = _seed_attachment_reviews(store, now)
    assignment_count = _seed_operational_assignments(store, now)
    shift_continuity_evidence_count = _seed_shift_continuity(store, now)

    store.upsert(
        namespace="demo_seed_metadata",
        record_key="current",
        payload={
            "version": DEMO_SEED_VERSION,
            "seeded_at": now.isoformat(),
            "job_count": len(jobs),
            "assignment_count": assignment_count,
            "attachment_review_count": attachment_review_count,
            "shift_continuity_evidence_count": shift_continuity_evidence_count,
            "fixed_rate_count": fixed_rate_count,
            "synthetic_only": True,
        },
        event_type="demo_database_seeded",
        entity_type="demo_seed_metadata",
    )
    return {
        "seeded": True,
        "db_path": str(db_path),
        "job_count": len(jobs),
        "customer_count": len(customers),
        "supplier_count": len(suppliers),
        "assignment_count": assignment_count,
        "attachment_review_count": attachment_review_count,
        "fixed_rate_count": fixed_rate_count,
        "shift_continuity_evidence_count": shift_continuity_evidence_count,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Seed the isolated MINAI synthetic demo database.")
    parser.add_argument("--db", required=True)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    print(seed_demo_database(args.db, reset=args.reset))
