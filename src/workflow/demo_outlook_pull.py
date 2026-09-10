from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os

from src.core.mail import InboundMailEnvelope
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.core.supplier_rfq import build_supplier_rfq_reference
from src.integrations.microsoft_auth import MicrosoftAuthConfig
from src.workflow.demo_inbound import parse_demo_customer_email
from src.workflow.outlook_pull import pull_controlled_outlook_inbox


class DemoSupplierResponseParser:
    """Deterministic commercial parser for the isolated synthetic mailbox."""

    def parse(self, safe_text):
        text = str(safe_text).casefold()
        if "demo:supplier_ack" in text:
            return SupplierResponseExtraction(status="acknowledged")
        if "demo:supplier_no_capacity" in text:
            return SupplierResponseExtraction(status="no_capacity")
        return SupplierResponseExtraction(
            status="quoted",
            cost=2380.0,
            currency="EUR",
            transit_time="5 gün",
            equipment_type="Tenteli / Curtainsider",
            pricing_basis="all_in",
        )


class DemoOutlookGraphReadClient:
    def __init__(self, *, access_token: str, mailbox_id: str, messages):
        self.access_token = access_token
        self.mailbox_id = mailbox_id
        self.messages = list(messages)
        self.last_message_rejections = []

    def list_inbox_messages(self, *, limit: int):
        return self.messages[:limit]


def _demo_messages(*, supplier_repository, now: datetime) -> list[InboundMailEnvelope]:
    mailbox = "ops@minai.invalid"
    messages = [
        InboundMailEnvelope(
            external_message_id="demo-outlook-customer-atlas-001",
            provider_name="microsoft_graph",
            mailbox_id=mailbox,
            sender_address="ops@atlas-tekstil.customer.invalid",
            sender_name="Atlas Tekstil Operasyon",
            recipient_addresses=[mailbox],
            subject="Adana Hamburg yeni fiyat talebi",
            body_text=(
                "DEMO:FTL\nMerhaba, Adana-Hamburg 20 ton tekstil için "
                "tenteli komple araç fiyatı rica ederiz."
            ),
            received_at=now,
            source="email",
        )
    ]

    state_dir = Path(os.environ.get("MINAI_DEMO_STATE_DIR", str(Path.home() / ".minai" / "demo"))).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    target_lock = state_dir / "demo_outlook_supplier_target.txt"
    locked_rfq_id = target_lock.read_text(encoding="utf-8").strip() if target_lock.exists() else ""
    supplier_target = supplier_repository.get_draft(locked_rfq_id) if locked_rfq_id else None
    if supplier_target is None:
        supplier_candidates = sorted(
            (
                draft for draft in supplier_repository.list_drafts()
                if draft.status == "awaiting_response"
                and draft.recipient_email
                and not supplier_repository.list_responses(draft.rfq_id)
                and (
                    supplier_repository.list_automated_sent_evidence(draft.rfq_id)
                    or supplier_repository.list_manual_sent_evidence(draft.rfq_id)
                )
            ),
            key=lambda draft: draft.rfq_id,
        )
        supplier_target = supplier_candidates[0] if supplier_candidates else None
        if supplier_target is not None:
            target_lock.write_text(supplier_target.rfq_id, encoding="utf-8")
    if supplier_target is not None:
        reference = build_supplier_rfq_reference(supplier_target.rfq_id)
        messages.append(InboundMailEnvelope(
            external_message_id=f"demo-outlook-supplier-{supplier_target.rfq_id}-001",
            provider_name="microsoft_graph",
            mailbox_id=mailbox,
            sender_address=supplier_target.recipient_email,
            sender_name=supplier_target.supplier_name,
            recipient_addresses=[mailbox],
            subject=f"Re: [{reference}] Teklifimiz",
            body_text="DEMO:SUPPLIER_QUOTE\nTeklifimiz 2380 EUR all-in, transit 5 gün.",
            received_at=now,
            explicit_rfq_reference=supplier_target.rfq_id,
            source="email",
        ))

    messages.append(InboundMailEnvelope(
        external_message_id="demo-outlook-unverified-001",
        provider_name="microsoft_graph",
        mailbox_id=mailbox,
        sender_address="unknown@unverified.invalid",
        sender_name="Bilinmeyen Gönderen",
        recipient_addresses=[mailbox],
        subject="Fiyat talebi",
        body_text="Bu gönderici müşteri veya tedarikçi master verisinde doğrulanmış değildir.",
        received_at=now,
        source="email",
    ))
    return messages


def run_demo_outlook_pull(
    *, limit: int, proposal_repository, operational_data_sources,
    master_data_repository, supplier_repository, attachment_review_repository,
    interpret_attachments: bool = False,
) -> dict:
    now = datetime.now(timezone.utc)
    messages = _demo_messages(supplier_repository=supplier_repository, now=now)
    config = MicrosoftAuthConfig(
        tenant_id="11111111-1111-1111-1111-111111111111",
        client_id="22222222-2222-2222-2222-222222222222",
        mailbox_id="ops@minai.invalid",
        token_cache_path=Path.home() / ".minai" / "demo" / "unused-token-cache.json",
    )

    def graph_factory(*, access_token, mailbox_id):
        return DemoOutlookGraphReadClient(
            access_token=access_token,
            mailbox_id=mailbox_id,
            messages=messages,
        )

    result = pull_controlled_outlook_inbox(
        config=config,
        limit=limit,
        shipment_parser=parse_demo_customer_email,
        proposal_repository=proposal_repository,
        operational_data_sources=operational_data_sources,
        master_data_repository=master_data_repository,
        supplier_parser=DemoSupplierResponseParser(),
        supplier_repository=supplier_repository,
        attachment_review_repository=attachment_review_repository,
        interpret_attachments=interpret_attachments,
        token_provider=lambda _config: "synthetic-demo-token-not-a-secret",
        graph_client_factory=graph_factory,
    )
    result["provider"] = "synthetic_demo_microsoft_graph"
    result["synthetic_mailbox"] = True
    result["synthetic_message_count"] = len(messages)
    return result
