from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts
from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.models import EquipmentDecision, Shipment
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteSupplierRFQRepository
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_lifecycle import approve_supplier_rfq
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_selection import select_suppliers_for_shipment

NOW = datetime(2026, 9, 11, 10, 30, tzinfo=timezone.utc)
CONTEXT = "mode=road|lane=turkiye>germany|equipment=tenteli"


def _supplier(repo, name: str):
    return create_supplier_master(
        repository=repo, entry_id=f"supplier:{name.casefold().replace(' ', '-')}",
        supplier_name=name, role="primary", reliability_score=0.7,
        price_score=0.7, speed_score=0.7, updated_by="Explainability Regression",
        created_at=NOW - timedelta(days=60),
    )


def _fact(repo, supplier, key: str, value: float, unit: str, *, context_key=None):
    observed = NOW - timedelta(days=5)
    fact = LearningFact(
        entry_id=f"explain:{supplier.supplier_id}:{context_key or 'global'}:{key}",
        subject_type="supplier", subject_id=supplier.supplier_id,
        subject_label=supplier.supplier_name, fact_key=key, context_key=context_key,
        value=value, value_unit=unit, confidence=1.0, source_type="operation_history",
        evidence=[LearningEvidence(
            source_type="operation_history", source_reference=f"explain:{key}:{context_key or 'global'}",
            observed_at=observed, summary="Synthetic reviewed supplier selection evidence.",
        )],
        status="confirmed", created_at=observed, created_by="Regression",
        updated_at=observed + timedelta(minutes=1), reviewed_at=observed + timedelta(minutes=1),
        reviewed_by="Regression Reviewer", review_note="Confirmed for explainability regression.",
    )
    repo.create(fact)
    return fact


def _shipment():
    return Shipment(
        customer_name="Synthetic", quote_mode="indicative", transport_mode="road",
        pickup_country="Türkiye", delivery_country="Germany", service_type="FTL",
        equipment_type="Tenteli",
    )


def _capabilities(*names):
    return [
        {
            "supplier_name": name, "role": "primary", "countries": ["Germany"],
            "route_regions": ["international"], "service_types": ["FTL"],
            "equipment_types": ["Tenteli"], "reliability_score": 0.7,
            "price_score": 0.7, "speed_score": 0.7,
            "notes": "Explainability regression capability record.",
        }
        for name in names
    ]


def evaluate_supplier_selection_explainability_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    learned = _supplier(masters, "Explained Primary")
    plain = _supplier(masters, "Plain Primary")
    facts = InMemoryLearningFactRepository()
    global_response = _fact(facts, learned, "response.median_minutes", 10, "minutes")
    global_quote = _fact(facts, learned, "commercial.usable_quote_rate_percent", 100, "percent")
    context_response = _fact(facts, learned, "response.median_minutes", 10, "minutes", context_key=CONTEXT)
    context_quote = _fact(facts, learned, "commercial.usable_quote_rate_percent", 100, "percent", context_key=CONTEXT)
    selection = select_suppliers_for_shipment(
        _shipment(), equipment_decision={"selected_equipment": "Tenteli"},
        risk_assessment={"risk_level": "green"},
        supplier_capabilities=_capabilities(learned.supplier_name, plain.supplier_name),
        master_data_repository=masters, learning_fact_repository=facts, policy_as_of=NOW,
    )
    first = selection["selected_suppliers"][0]
    check(
        first["supplier_name"] == learned.supplier_name
        and first["learning_adjustment"] == 0.06
        and first["learning_adjustment_capped"] is True
        and set(first["global_learning_fact_ids"]) == {global_response.fact_id, global_quote.fact_id}
        and set(first["context_learning_fact_ids"]) == {context_response.fact_id, context_quote.fact_id}
        and first["learning_context_key"] == CONTEXT,
        "selection engine exposes bounded global and contextual ranking provenance without changing eligibility",
    )

    equipment = EquipmentDecision(
        selected_equipment="Tenteli", reason="Synthetic equipment decision.", confidence=1.0,
    )
    drafts = generate_supplier_rfq_drafts(
        shipment=_shipment(), equipment_decision=equipment,
        supplier_selection=selection, workflow_id="explain-workflow",
    )
    explained = drafts[0]
    snapshot = explained.selection_explanation
    check(
        snapshot is not None and snapshot.selection_rank == 1
        and snapshot.eligibility_passed is True
        and snapshot.eligibility_basis == "route_service_equipment"
        and snapshot.combined_learning_adjustment == 0.06
        and snapshot.learning_adjustment_capped is True,
        "generated RFQ stores a bounded selection explanation snapshot instead of relying on future recomputation",
    )
    check(
        snapshot is not None
        and set(snapshot.global_learning_fact_ids) == {global_response.fact_id, global_quote.fact_id}
        and set(snapshot.context_learning_fact_ids) == {context_response.fact_id, context_quote.fact_id}
        and snapshot.learning_context_key == CONTEXT
        and snapshot.selection_strategy == selection["selection_strategy"]
        and snapshot.data_source == selection["data_source"],
        "selection snapshot preserves reviewed fact ids, shipment context, strategy and capability data source",
    )

    rfqs = InMemorySupplierRFQRepository()
    workflow = SupplierRFQWorkflow(
        workflow_id="explain-workflow", shipment=_shipment(), rfq_ids=[explained.rfq_id],
    )
    rfqs.save_workflow(workflow); rfqs.save_drafts([explained])
    approved = approve_supplier_rfq(
        repository=rfqs, rfq_id=explained.rfq_id,
        approved_by="Regression Operator", approved_at=NOW + timedelta(minutes=5),
    )
    check(
        approved.status == "approved"
        and approved.selection_explanation == snapshot,
        "RFQ lifecycle transitions preserve the original supplier selection explanation unchanged",
    )

    first["total_score"] = 0.01
    first["reason"] = "Mutated transient selection result that must not rewrite durable history."
    persisted = rfqs.get_draft(explained.rfq_id)
    check(
        persisted is not None and persisted.selection_explanation == snapshot
        and persisted.selection_explanation.total_score != 0.01,
        "later in-memory selection changes cannot rewrite the durable historical selection snapshot",
    )
    with tempfile.TemporaryDirectory() as tmp:
        store = SQLitePilotStore(Path(tmp) / "selection-explain.sqlite3")
        durable = SQLiteSupplierRFQRepository(store)
        durable.save_workflow(workflow); durable.save_drafts([explained])
        reopened = SQLiteSupplierRFQRepository(SQLitePilotStore(Path(tmp) / "selection-explain.sqlite3"))
        durable_draft = reopened.get_draft(explained.rfq_id)
        check(
            durable_draft is not None and durable_draft.selection_explanation == snapshot,
            "selection explanation survives durable SQLite supplier-RFQ repository reconstruction",
        )

    legacy = SupplierRFQDraft(
        rfq_id="legacy-rfq", workflow_id="legacy-workflow", supplier_name="Legacy Supplier",
        priority=1, dispatch_tier="primary", subject="Legacy", body="Legacy RFQ",
    )
    check(
        legacy.selection_explanation is None,
        "legacy supplier RFQs remain readable when no historical selection snapshot exists",
    )

    root = Path(__file__).resolve().parents[2]
    ui = (root / "ui/web_shell/app.js").read_text(encoding="utf-8")
    job_view = (root / "src/core/mina_job_view.py").read_text(encoding="utf-8")
    check(
        '"selection_explanation"' in job_view
        and "Neden seçildi?" in ui and "Eligibility geçti" in ui
        and "güvenlik sınırında cap uygulandı" in ui,
        "MINA job read model and browser expose the durable selection explanation and learning cap visibly",
    )
    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier selection explainability regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome = evaluate_supplier_selection_explainability_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
