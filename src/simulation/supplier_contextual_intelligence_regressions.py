from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import InMemoryLearningFactRepository, SQLiteLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact, create_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.models import Shipment
from src.core.pilot_store import SQLitePilotStore
from src.core.supplier_context import shipment_context_keys
from src.core.supplier_intelligence_policy import (
    build_supplier_operational_learning_policy,
    resolve_supplier_contextual_learning_overlay,
)
from src.core.supplier_learning_service import derive_supplier_history_learning
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_selection import select_suppliers_for_shipment

NOW = datetime(2026, 9, 11, 8, 30, tzinfo=timezone.utc)


def _supplier(repo, name: str, *, role: str = "primary"):
    return create_supplier_master(
        repository=repo,
        entry_id=f"supplier:{name.casefold().replace(' ', '-')}",
        supplier_name=name,
        role=role,
        reliability_score=0.7,
        price_score=0.7,
        speed_score=0.7,
        updated_by="Context Regression",
        created_at=NOW - timedelta(days=90),
    )


def _add_history(repo, supplier_name: str, country: str, minutes: list[int], *, quoted: bool):
    for index, response_minutes in enumerate(minutes):
        rfq_id = f"{country.casefold()}-{index}-{response_minutes}"
        workflow_id = f"wf-{rfq_id}"
        shipment = Shipment(
            customer_name="Synthetic",
            transport_mode="road",
            pickup_country="Türkiye",
            delivery_country=country,
            service_type="FTL",
            equipment_type="Tenteli",
        )
        workflow = SupplierRFQWorkflow(
            workflow_id=workflow_id,
            shipment=shipment,
            rfq_ids=[rfq_id],
        )
        sent_at = NOW - timedelta(days=20 - index, hours=2)
        draft = SupplierRFQDraft(
            rfq_id=rfq_id,
            workflow_id=workflow_id,
            supplier_name=supplier_name,
            priority=1,
            recipient_email="context@example.invalid",
            supplier_role="primary",
            dispatch_tier="primary",
            subject="RFQ",
            body="RFQ",
            status="awaiting_response",
            sent_at=sent_at,
        )
        response = SupplierRFQResponse(
            rfq_id=rfq_id,
            supplier_name=supplier_name,
            rfq_priority=1,
            status="quoted" if quoted else "declined",
            cost=2200.0 if quoted else None,
            currency="EUR" if quoted else None,
            received_at=sent_at + timedelta(minutes=response_minutes),
            source="email",
        )
        repo.save_workflow(workflow)
        repo.save_drafts([draft])
        repo.save_responses([response])


def _capabilities(*names):
    return [
        {
            "supplier_name": name,
            "role": "backup" if "Backup" in name else "primary",
            "countries": ["Germany", "France", "Spain"],
            "route_regions": ["international"],
            "service_types": ["FTL"],
            "equipment_types": ["Tenteli"],
            "reliability_score": 0.7,
            "price_score": 0.7,
            "speed_score": 0.7,
            "notes": "context regression",
        }
        for name in names
    ]


def _select(country, masters, facts, capabilities):
    return select_suppliers_for_shipment(
        Shipment(
            customer_name="Synthetic", transport_mode="road",
            pickup_country="Türkiye", delivery_country=country,
            service_type="FTL", equipment_type="Tenteli",
        ),
        equipment_decision={"selected_equipment": "Tenteli"},
        risk_assessment={"risk_level": "green"},
        supplier_capabilities=capabilities,
        master_data_repository=masters,
        learning_fact_repository=facts,
        policy_as_of=NOW,
    )


def evaluate_supplier_contextual_intelligence_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    context_keys = shipment_context_keys(Shipment(
        customer_name="Synthetic", transport_mode="road",
        pickup_country="Türkiye", delivery_country="Germany",
        equipment_type="Tenteli",
    ))
    check(
        context_keys == [
            "mode=road|lane=turkiye>germany|equipment=tenteli",
            "mode=road|lane=turkiye>germany",
        ],
        "supplier context keys are deterministic and prefer lane-plus-equipment specificity",
    )

    invalid_context_blocked = False
    try:
        create_learning_fact(
            repository=InMemoryLearningFactRepository(), entry_id="invalid-context",
            subject_type="supplier", subject_id="supplier-placeholder", subject_label="Supplier",
            fact_key="response.median_minutes", context_key="free text context",
            value=20, value_unit="minutes", confidence=0.9, source_type="manual",
            evidence=[LearningEvidence(
                source_type="manual", source_reference="invalid-context-evidence",
                observed_at=NOW, summary="Invalid context format regression.",
            )], created_by="Context Regression", occurred_at=NOW,
        )
    except ValueError:
        invalid_context_blocked = True
    check(invalid_context_blocked, "free-text supplier context keys are rejected fail-closed")

    non_supplier_context_blocked = False
    try:
        create_learning_fact(
            repository=InMemoryLearningFactRepository(), entry_id="route-context",
            subject_type="route", subject_id="tr-de", subject_label="TR-DE",
            fact_key="response.median_minutes",
            context_key="mode=road|lane=turkiye>germany",
            value=20, value_unit="minutes", confidence=0.9, source_type="manual",
            evidence=[LearningEvidence(
                source_type="manual", source_reference="route-context-evidence",
                observed_at=NOW, summary="Non-supplier context regression.",
            )], created_by="Context Regression", occurred_at=NOW,
        )
    except ValueError:
        non_supplier_context_blocked = True
    check(non_supplier_context_blocked, "context_key authority is restricted to supplier learning facts")

    masters = InMemoryMasterDataRepository()
    learned = _supplier(masters, "Context Primary")
    plain = _supplier(masters, "Plain Primary")
    backup = _supplier(masters, "Context Backup", role="backup")
    facts = InMemoryLearningFactRepository()
    rfqs = InMemorySupplierRFQRepository()
    _add_history(rfqs, learned.supplier_name, "Germany", [10, 20, 30, 40, 50, 60], quoted=True)
    _add_history(rfqs, learned.supplier_name, "France", [240, 270, 300, 330, 360, 390], quoted=False)
    derived = derive_supplier_history_learning(
        supplier_id=learned.supplier_id,
        master_repository=masters,
        supplier_repository=rfqs,
        learning_repository=facts,
        created_by="Context Regression",
        occurred_at=NOW,
    )
    contextual = [item for item in facts.list_all() if item.context_key]
    exact_de = "mode=road|lane=turkiye>germany|equipment=tenteli"
    exact_fr = "mode=road|lane=turkiye>france|equipment=tenteli"
    check(
        derived["contextual_proposed_fact_count"] == 8
        and len(contextual) == 8
        and {item.context_key for item in contextual} == {
            exact_de, "mode=road|lane=turkiye>germany",
            exact_fr, "mode=road|lane=turkiye>france",
        }
        and all(item.status == "proposed" for item in contextual),
        "durable RFQ history derives proposed lane and lane-equipment supplier metrics only with enough samples",
    )

    de_facts = [item for item in contextual if item.context_key == exact_de]
    fr_facts = [item for item in contextual if item.context_key == exact_fr]
    for item in de_facts + fr_facts:
        confirm_learning_fact(
            repository=facts,
            fact_id=item.fact_id,
            reviewed_by="Context Reviewer",
            review_note="Confirmed contextual supplier history.",
            occurred_at=NOW + timedelta(minutes=1),
        )

    global_policy = build_supplier_operational_learning_policy(
        supplier=learned,
        learning_repository=facts,
        base_first_reminder_minutes=30,
        base_acknowledged_wait_minutes=120,
        as_of=NOW + timedelta(minutes=2),
    )
    de_overlay = resolve_supplier_contextual_learning_overlay(
        supplier_name=learned.supplier_name,
        context_key=exact_de,
        master_data_repository=masters,
        learning_repository=facts,
        as_of=NOW + timedelta(minutes=2),
    )
    fr_overlay = resolve_supplier_contextual_learning_overlay(
        supplier_name=learned.supplier_name,
        context_key=exact_fr,
        master_data_repository=masters,
        learning_repository=facts,
        as_of=NOW + timedelta(minutes=2),
    )
    check(
        global_policy.ranking_adjustment == 0
        and global_policy.first_reminder_source == "dispatch_default"
        and de_overlay is not None and de_overlay.ranking_adjustment > 0
        and fr_overlay is not None and fr_overlay.ranking_adjustment < 0,
        "context facts stay isolated from global reminder policy while producing bounded lane-specific ranking overlays",
    )

    capabilities = _capabilities(learned.supplier_name, plain.supplier_name, backup.supplier_name)
    de_selection = _select("Germany", masters, facts, capabilities)["selected_suppliers"]
    fr_selection = _select("France", masters, facts, capabilities)["selected_suppliers"]
    es_selection = _select("Spain", masters, facts, capabilities)["selected_suppliers"]
    de_learned = next(item for item in de_selection if item["supplier_name"] == learned.supplier_name)
    fr_learned = next(item for item in fr_selection if item["supplier_name"] == learned.supplier_name)
    es_learned = next(item for item in es_selection if item["supplier_name"] == learned.supplier_name)
    check(
        de_selection[0]["supplier_name"] == learned.supplier_name
        and de_learned["context_learning_adjustment"] > 0
        and de_learned["learning_context_key"] == exact_de
        and fr_selection[0]["supplier_name"] == plain.supplier_name
        and fr_learned["context_learning_adjustment"] < 0
        and fr_learned["learning_context_key"] == exact_fr
        and es_learned["context_learning_adjustment"] == 0
        and es_learned["learning_context_key"] is None,
        "confirmed contextual learning affects only the matching shipment context and never leaks to an unrelated lane",
    )
    check(
        all(item["dispatch_tier"] == "primary" for item in de_selection[:-1])
        and de_selection[-1]["supplier_name"] == backup.supplier_name
        and de_selection[-1]["dispatch_tier"] == "secondary",
        "contextual learning preserves primary-before-secondary dispatch tier authority",
    )

    global_proposed = next(
        item for item in facts.list_all()
        if item.context_key is None and item.fact_key == "response.median_minutes"
    )
    confirmed_global = confirm_learning_fact(
        repository=facts, fact_id=global_proposed.fact_id,
        reviewed_by="Context Reviewer", review_note="Confirm global supplier response metric.",
        occurred_at=NOW + timedelta(minutes=3),
    )
    check(
        confirmed_global.status == "confirmed"
        and any(item.status == "confirmed" and item.context_key == exact_de for item in facts.list_all()),
        "global and contextual facts for the same supplier metric can hold separate reviewed authority",
    )

    de_response_confirmed = next(
        item for item in facts.list_all()
        if item.status == "confirmed" and item.context_key == exact_de
        and item.fact_key == "response.median_minutes"
    )
    _add_history(rfqs, learned.supplier_name, "Germany", [300], quoted=True)
    derive_supplier_history_learning(
        supplier_id=learned.supplier_id,
        master_repository=masters,
        supplier_repository=rfqs,
        learning_repository=facts,
        created_by="Context Regression",
        occurred_at=NOW + timedelta(minutes=4),
    )
    replacement = [
        item for item in facts.list_all()
        if item.status == "proposed" and item.context_key == exact_de
        and item.fact_key == "response.median_minutes"
        and item.supersedes_fact_id == de_response_confirmed.fact_id
    ]
    check(
        len(replacement) == 1 and replacement[0].value == 40.0,
        "changed context history creates a replacement proposal instead of overwriting confirmed contextual authority",
    )

    stale_supplier = _supplier(masters, "Stale Context")
    stale_context = "mode=road|lane=turkiye>germany|equipment=tenteli"
    stale_fact = create_learning_fact(
        repository=facts, entry_id="stale-context-response",
        subject_type="supplier", subject_id=stale_supplier.supplier_id,
        subject_label=stale_supplier.supplier_name, fact_key="response.median_minutes",
        context_key=stale_context, value=15, value_unit="minutes", confidence=0.99,
        source_type="operation_history",
        evidence=[LearningEvidence(
            source_type="operation_history", source_reference="stale-context-evidence",
            observed_at=NOW - timedelta(days=500),
            summary="Old context evidence must decay before runtime ranking.",
        )],
        created_by="Context Regression", occurred_at=NOW - timedelta(days=500),
        master_repository=masters,
    )
    confirm_learning_fact(
        repository=facts, fact_id=stale_fact.fact_id,
        reviewed_by="Context Reviewer", review_note="Review stale context evidence.",
        occurred_at=NOW - timedelta(days=499),
    )
    stale_overlay = resolve_supplier_contextual_learning_overlay(
        supplier_name=stale_supplier.supplier_name, context_key=stale_context,
        master_data_repository=masters, learning_repository=facts, as_of=NOW,
    )
    check(
        stale_overlay is not None and stale_overlay.ranking_adjustment == 0
        and stale_overlay.evaluations[0].reason == "evidence_too_old_for_runtime_effect",
        "stale contextual evidence may be reviewed but cannot influence current supplier ranking",
    )

    with tempfile.TemporaryDirectory() as temp:
        store = SQLitePilotStore(Path(temp) / "context.sqlite3")
        durable = SQLiteLearningFactRepository(store)
        durable_fact = create_learning_fact(
            repository=durable, entry_id="durable-context-fact",
            subject_type="supplier", subject_id=learned.supplier_id,
            subject_label=learned.supplier_name, fact_key="response.median_minutes",
            context_key=exact_de, value=33, value_unit="minutes", confidence=0.85,
            source_type="operation_history",
            evidence=[LearningEvidence(
                source_type="operation_history", source_reference="durable-context-evidence",
                observed_at=NOW - timedelta(days=2), summary="Durable context evidence.",
            )],
            created_by="Context Regression", occurred_at=NOW,
        )
        roundtrip = durable.get(durable_fact.fact_id)
        check(
            roundtrip is not None and roundtrip.context_key == exact_de,
            "context_key survives durable SQLite learning-fact round trip",
        )

    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier contextual intelligence regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome = evaluate_supplier_contextual_intelligence_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
