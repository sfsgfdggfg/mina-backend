from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact
from src.core.master_data import CustomerMasterProfile, MasterContact, SupplierMasterProfile
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.privacy import PrivacySafeText
from src.core.relationship_history import (
    HistoricalMailMessage, RelationshipAIObservation, RelationshipAIObservationSet,
    analyze_relationship_history,
)
from src.core.pilot_access import route_allowed
from src.integrations.microsoft_auth import MicrosoftAuthConfig
from src.integrations.outlook_graph import OutlookGraphReadClient
from src.workflow.relationship_onboarding import (
    RelationshipOnboardingAuthorizationError, run_outlook_relationship_onboarding,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
AGENCY = "ops@agency.invalid"


class _AI:
    def __init__(self): self.calls=[]
    def analyze(self, *, subject_type, history_text):
        assert isinstance(history_text, PrivacySafeText)
        assert "contact@customer.invalid" not in str(history_text)
        assert "+90 555 111 2233" not in str(history_text)
        self.calls.append((subject_type, str(history_text)))
        if subject_type == "supplier":
            return RelationshipAIObservationSet(observations=[RelationshipAIObservation(
                category="negotiation_behavior", observation="Often responds after a concrete target is supplied.", confidence=.82
            )])
        return RelationshipAIObservationSet(observations=[RelationshipAIObservation(
            category="quote_preference", observation="Usually asks for a concise price-first reply.", confidence=.74
        )])


def _masters():
    repo=InMemoryMasterDataRepository()
    customer=CustomerMasterProfile(
        entry_id="customer-1", customer_name="Customer One", trusted_sender_domains=["customer.invalid"],
        contacts=[MasterContact(contact_name="Customer",email="contact@customer.invalid",is_primary=True)],
        created_at=NOW,updated_at=NOW,updated_by="Tester",
    )
    supplier=SupplierMasterProfile(
        entry_id="supplier-1", supplier_name="Supplier One",
        contacts=[MasterContact(contact_name="Pricing",email="pricing@supplier.invalid",roles=["pricing"],is_primary=True)],
        created_at=NOW,updated_at=NOW,updated_by="Tester",
    )
    ambiguous_customer=CustomerMasterProfile(
        entry_id="customer-2", customer_name="Ambiguous Customer",
        contacts=[MasterContact(email="dup@shared.invalid")],created_at=NOW,updated_at=NOW,updated_by="Tester",
    )
    ambiguous_supplier=SupplierMasterProfile(
        entry_id="supplier-2", supplier_name="Ambiguous Supplier",
        contacts=[MasterContact(email="dup@shared.invalid")],created_at=NOW,updated_at=NOW,updated_by="Tester",
    )
    for item in (customer,ambiguous_customer): repo.create_customer(item)
    for item in (supplier,ambiguous_supplier): repo.create_supplier(item)
    return repo,customer,supplier


def _mail(ref, minutes, sender, recipients, subject, body):
    return HistoricalMailMessage(
        source_reference=ref,sent_at=NOW+timedelta(minutes=minutes),sender_address=sender,
        recipient_addresses=recipients,subject=subject,body_text=body,source="synthetic",
    )


def _history():
    return [
        _mail("c1",0,AGENCY,["contact@customer.invalid"],"Munich quote","Please advise."),
        _mail("c2",30,"sales@customer.invalid",[AGENCY],"Re: Munich quote","Thanks. contact@customer.invalid +90 555 111 2233"),
        _mail("c3",60,"sales@customer.invalid",[AGENCY],"Urgent update","Any update?"),
        _mail("c4",70,AGENCY,["sales@customer.invalid"],"Re: Urgent update","Working on it."),
        _mail("s1",120,AGENCY,["pricing@supplier.invalid"],"DE load","Can you quote?"),
        _mail("s2",165,"pricing@supplier.invalid",[AGENCY],"Re: DE load","We can offer a price."),
        _mail("s2",165,"pricing@supplier.invalid",[AGENCY],"Re: DE load","We can offer a price."),
        _mail("u1",180,"unknown@unknown.invalid",[AGENCY],"Hello","Unknown counterparty"),
        _mail("a1",190,"dup@shared.invalid",[AGENCY],"Hello","Ambiguous counterparty"),
    ]


class _Response:
    def __init__(self,payload): self.status_code=200; self._payload=payload; self.headers={}
    def json(self): return self._payload


class _Session:
    def __init__(self): self.calls=[]; self.trust_env=True
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs.get("params")))
        base={
            "id":"hist-1","subject":"History","body":{"contentType":"text","content":"Body"},
            "from":{"emailAddress":{"address":"pricing@supplier.invalid"}},
            "toRecipients":[{"emailAddress":{"address":AGENCY}}],"isDraft":False,
            "receivedDateTime":"2026-09-01T09:00:00Z","sentDateTime":"2026-09-01T08:59:00Z",
        }
        if "/inbox/" in url:
            return _Response({"value":[base]})
        sent=dict(base); sent.update({
            "id":"hist-2","from":{"emailAddress":{"address":AGENCY}},
            "toRecipients":[{"emailAddress":{"address":"pricing@supplier.invalid"}}],
            "sentDateTime":"2026-09-01T08:00:00Z",
        })
        return _Response({"value":[sent]})


def evaluate_relationship_history_onboarding_regressions():
    failures=[]; passes=[]
    def check(condition,label): (passes if condition else failures).append(label)

    masters,customer,supplier=_masters(); learning=InMemoryLearningFactRepository(); ai=_AI()
    result=analyze_relationship_history(
        messages=_history(),agency_addresses=[AGENCY],master_repository=masters,
        learning_repository=learning,created_by="Tester",ai_analyzer=ai,occurred_at=NOW+timedelta(hours=4),
    )
    check(
        result.input_message_count==9 and result.unique_message_count==8 and result.duplicate_message_count==1
        and result.matched_message_count==6 and result.unmatched_message_count==1 and result.ambiguous_message_count==1,
        "history onboarding deduplicates and refuses unmatched or ambiguous master-data identity",
    )
    customer_summary=next(x for x in result.subjects if x.subject_type=="customer")
    supplier_summary=next(x for x in result.subjects if x.subject_type=="supplier")
    check(
        customer_summary.message_count==4 and customer_summary.counterparty_response_sample_count==1
        and customer_summary.agency_response_sample_count==1
        and supplier_summary.message_count==2 and supplier_summary.counterparty_response_sample_count==1,
        "customer and supplier thread response evidence is separated by relationship direction",
    )
    facts=learning.list_all()
    supplier_response=next(x for x in facts if x.subject_id==supplier.supplier_id and x.fact_key=="history.email.counterparty_response_median_minutes")
    check(
        supplier_response.value==45.0 and supplier_response.status=="proposed"
        and all("Body" not in ev.summary and "contact@customer.invalid" not in ev.summary for fact in facts for ev in fact.evidence)
        and result.raw_body_persisted is False,
        "deterministic mail metrics persist aggregate evidence without raw historical bodies",
    )
    check(
        len(ai.calls)==2 and any(x.fact_key=="relationship.negotiation_behavior" and x.source_type=="minai_inference" for x in facts)
        and any(x.fact_key=="relationship.quote_preference" and x.subject_id==customer.customer_id for x in facts),
        "AI relationship observations receive privacy-safe history and remain proposed facts",
    )

    # The product deliberately supports a deterministic first pass followed by an AI-on rerun
    # over the exact same historical evidence. Existing metric proposals must be reused/skipped,
    # while only previously absent AI categories are created.
    phased_learning=InMemoryLearningFactRepository()
    first_pass=analyze_relationship_history(
        messages=_history(),agency_addresses=[AGENCY],master_repository=masters,
        learning_repository=phased_learning,created_by="Tester",ai_analyzer=None,
        occurred_at=NOW+timedelta(hours=10),
    )
    first_count=len(phased_learning.list_all())
    phased_ai=_AI()
    second_pass=analyze_relationship_history(
        messages=_history(),agency_addresses=[AGENCY],master_repository=masters,
        learning_repository=phased_learning,created_by="Tester",ai_analyzer=phased_ai,
        occurred_at=NOW+timedelta(hours=11),
    )
    after_second=phased_learning.list_all()
    second_count=len(after_second)
    second_ai_keys={
        item.fact_key for item in after_second if item.source_type=="minai_inference"
    }
    third_ai=_AI()
    third_pass=analyze_relationship_history(
        messages=_history(),agency_addresses=[AGENCY],master_repository=masters,
        learning_repository=phased_learning,created_by="Tester",ai_analyzer=third_ai,
        occurred_at=NOW+timedelta(hours=12),
    )
    check(
        first_pass.ai_observation_count==0
        and second_pass.ai_observation_count==2
        and second_count==first_count+2
        and second_ai_keys=={"relationship.negotiation_behavior","relationship.quote_preference"}
        and third_pass.proposed_fact_count==0
        and len(phased_learning.list_all())==second_count,
        "phased deterministic then AI history reruns are idempotent and add only missing observation categories",
    )

    confirmed=confirm_learning_fact(
        repository=learning,fact_id=supplier_response.fact_id,reviewed_by="Tester",
        review_note="Synthetic confirmation",occurred_at=NOW+timedelta(hours=5),
    )
    replacement=analyze_relationship_history(
        messages=[
            _mail("s3",300,AGENCY,["pricing@supplier.invalid"],"NL load","Can you quote?"),
            _mail("s4",420,"pricing@supplier.invalid",[AGENCY],"Re: NL load","Later reply"),
        ],agency_addresses=[AGENCY],master_repository=masters,learning_repository=learning,
        created_by="Tester",occurred_at=NOW+timedelta(hours=8),
    )
    replacement_fact=next(
        x for x in learning.list_all()
        if x.status=="proposed" and x.fact_key==confirmed.fact_key and x.supersedes_fact_id==confirmed.fact_id
    )
    check(
        replacement.proposed_fact_count>0 and replacement_fact.value==120.0,
        "new history that changes confirmed knowledge creates a replacement proposal instead of overwriting authority",
    )

    session=_Session(); client=OutlookGraphReadClient(access_token="token",mailbox_id=AGENCY,session=session)
    graph_history=client.list_relationship_history(
        start_at=datetime(2026,9,1,tzinfo=UTC),end_at=datetime(2026,9,2,tzinfo=UTC),max_messages=10,
    )
    filters=[call[2].get("$filter") for call in session.calls if call[2]]
    check(
        len(graph_history)==2 and all(item.source=="authorized_mailbox" for item in graph_history)
        and any("receivedDateTime ge" in value for value in filters)
        and any("sentDateTime ge" in value for value in filters),
        "Outlook history reader scans bounded inbox and sent-items ranges without changing daily pull semantics",
    )

    token_calls=[]
    config=MicrosoftAuthConfig(tenant_id="consumers",client_id="00000000-0000-0000-0000-000000000001",mailbox_id=AGENCY,token_cache_path=Path("/tmp/x"))
    try:
        run_outlook_relationship_onboarding(
            config=config,start_at=NOW,end_at=NOW+timedelta(days=1),max_messages=10,
            authorization_confirmed=False,master_repository=masters,learning_repository=learning,
            created_by="Tester",token_provider=lambda cfg: token_calls.append(cfg) or "token",
        )
        blocked=False
    except RelationshipOnboardingAuthorizationError:
        blocked=True
    check(blocked and not token_calls,"Outlook history onboarding requires explicit authorization before token or mailbox access")

    root=Path(__file__).resolve().parents[2]
    api=(root/"src/api.py").read_text(encoding="utf-8")
    ui=(root/"ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        route_allowed("GET","/relationship-onboarding/status")
        and route_allowed("POST","/relationship-onboarding/outlook/analyze")
        and "authorization_confirmed" in api and "include_ai_observations" in api,
        "controlled pilot exposes explicit bounded relationship-onboarding authority",
    )
    check(
        "İlişki Hafızası" in ui and "Bu mailbox geçmişini seçilen tarih aralığında analiz etmeye yetkim var." in ui
        and "/relationship-onboarding/outlook/analyze" in ui and "raw_messages_persisted" in ui
        and "window.prompt" not in ui and "localStorage" not in ui and "sessionStorage" not in ui,
        "browser makes historical mailbox access an explicit operator action and keeps browser state server-authoritative",
    )
    return {"passed":not failures,"passes":passes,"failures":failures}


if __name__=="__main__":
    result=evaluate_relationship_history_onboarding_regressions()
    for label in result["passes"]: print(f"PASS {label}")
    for label in result["failures"]: print(f"FAIL {label}")
    print("\nRelationship history onboarding regressions: "+("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
