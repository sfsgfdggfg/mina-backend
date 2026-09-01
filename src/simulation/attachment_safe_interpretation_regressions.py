from __future__ import annotations

from src.core.attachment_safe_extraction import SafeAttachmentExtractionArtifact, SafeExtractedTable
from src.core.attachment_safe_interpretation import (
    MAX_ATTACHMENT_INTERPRETATION_INPUT_CHARS,
    build_attachment_interpretation_sections,
    interpret_extracted_attachment_mail,
)
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.mail import InboundMailEnvelope
from src.core.models import Shipment
from src.core.privacy import PrivacySafeText
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.simulation.outlook_inbound_router_regressions import _mail


PRIVATE_EMAIL = "person@example.com"
PRIVATE_PHONE = "+90 532 123 45 67"


def _proposal():
    return ShipmentProposalSnapshot.model_validate(Shipment(customer_name="Unknown Customer").model_dump())


def _text_artifact(text="Rate is 2300 EUR"):
    return SafeAttachmentExtractionArtifact(
        name="private.pdf", content_profile="pdf", extraction_kind="text",
        text=text, character_count=len(text), table_count=0, cell_count=0,
    )


def _table_artifact():
    rows = [["Cost", "2300 EUR"], ["Email", PRIVATE_EMAIL]]
    return SafeAttachmentExtractionArtifact(
        name="quote.xlsx", content_profile="xlsx", extraction_kind="tables",
        tables=[SafeExtractedTable(name="sheet1", rows=rows, row_count=2, column_count=2, cell_count=4)],
        character_count=sum(len(c) for r in rows for c in r), table_count=1, cell_count=4,
    )


class _SupplierParser:
    def __init__(self): self.calls=[]
    def parse(self, safe_text):
        self.calls.append(safe_text)
        return SupplierResponseExtraction(status="quoted", cost=2300.0, currency="EUR")


def evaluate_attachment_safe_interpretation_regressions():
    failures=[]; passes=[]
    def check(condition,label): (passes if condition else failures).append(label)

    customer_calls=[]
    def customer_parser(safe_text):
        customer_calls.append(safe_text)
        return _proposal()

    mail = _mail(sender="ops@pilot.example", message_id="interpret-core", subject="Quote " + PRIVATE_EMAIL).model_copy(
        update={"body_text": "Call " + PRIVATE_PHONE}
    )
    artifacts=[_text_artifact("Supplier contact " + PRIVATE_EMAIL + " rate 2300 EUR"), _table_artifact()]
    result=interpret_extracted_attachment_mail(
        mail=mail, artifacts=artifacts, route="customer", shipment_parser=customer_parser, supplier_parser=None,
    )
    safe=str(customer_calls[0])
    serialized=result.model_dump_json()
    check(
        result.status=="interpreted" and result.parser_called and isinstance(customer_calls[0], PrivacySafeText)
        and "EMAIL_SUBJECT" in safe and "EMAIL_BODY" in safe and "ATTACHMENT_1_PDF" in safe
        and PRIVATE_EMAIL not in safe and PRIVATE_PHONE not in safe
        and result.customer_proposal is not None
        and result.source_profiles == ["pdf", "xlsx"],
        "customer attachment bundle is privacy transformed with safe source profiles",
    )
    check(
        "customer_proposal" not in serialized and "2300" not in repr(result),
        "interpreted customer payload is excluded from serialization and repr",
    )

    supplier=_SupplierParser()
    supplier_result=interpret_extracted_attachment_mail(
        mail=mail, artifacts=[_text_artifact()], route="supplier", shipment_parser=customer_parser, supplier_parser=supplier,
    )
    check(
        supplier_result.status=="interpreted" and len(supplier.calls)==1
        and isinstance(supplier.calls[0], PrivacySafeText)
        and supplier_result.supplier_extraction is not None,
        "supplier attachment interpretation yields non-authoritative commercial extraction",
    )

    class _InvalidSupplierParser:
        def parse(self, safe_text):
            return {"status": "quoted", "cost": "not-a-number", "currency": "EUR"}

    invalid=interpret_extracted_attachment_mail(
        mail=mail, artifacts=[_text_artifact()], route="supplier", shipment_parser=customer_parser,
        supplier_parser=_InvalidSupplierParser(),
    )
    check(
        invalid.status=="manual_review" and invalid.reason_code=="attachment_supplier_interpretation_failed"
        and invalid.parser_called is True,
        "invalid supplier interpretation output fails closed",
    )

    missing=interpret_extracted_attachment_mail(
        mail=mail, artifacts=[_text_artifact()], route="supplier", shipment_parser=customer_parser, supplier_parser=None,
    )
    check(
        missing.status=="manual_review" and missing.reason_code=="attachment_supplier_parser_not_available"
        and missing.parser_called is False,
        "missing supplier parser fails closed before interpretation",
    )

    huge=_text_artifact("X" * (MAX_ATTACHMENT_INTERPRETATION_INPUT_CHARS + 1))
    huge = huge.model_copy(update={"character_count": len(huge.text or "")})
    oversized=interpret_extracted_attachment_mail(
        mail=mail.model_copy(update={"subject":None,"body_text":""}), artifacts=[huge], route="customer",
        shipment_parser=customer_parser, supplier_parser=None,
    )
    check(
        oversized.status=="manual_review" and oversized.reason_code=="attachment_interpretation_privacy_or_size_block"
        and len(customer_calls)==1,
        "oversized interpretation bundle is rejected without truncation or parser call",
    )

    sections=build_attachment_interpretation_sections(mail,[ _table_artifact() ])
    check(any(label=="ATTACHMENT_1_XLSX" and '2300 EUR' in text for label,text in sections),
          "table extraction is rendered deterministically for the privacy boundary")
    return {"name":"Safe attachment interpretation","passed":not failures,"failures":failures,"passed_checks":passes}


def main():
    result=evaluate_attachment_safe_interpretation_regressions()
    for label in result["passed_checks"]: print("PASS",label)
    for label in result["failures"]: print("FAIL",label)
    print("\nSafe attachment interpretation regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
