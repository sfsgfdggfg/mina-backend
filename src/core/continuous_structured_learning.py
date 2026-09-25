from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.customer_preference_learning import derive_customer_preference_learning
from src.core.customer_preference_policy import (
    COMMERCIAL_ACCEPTED_CURRENCY_KEY,
    PREFERENCE_FACT_FIELDS,
)
from src.core.customer_quote_acceptance_learning import (
    derive_customer_quote_acceptance_learning,
)
from src.core.customer_quote_acceptance_policy import SUPPORTED_QUOTE_ACCEPTANCE_FACTS
from src.core.customer_quote_reason_learning import derive_customer_quote_reason_learning
from src.core.customer_quote_reason_policy import SUPPORTED_CUSTOMER_QUOTE_REASON_FACTS
from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_learning_service import derive_supplier_history_learning
from src.core.supplier_price_repository import SupplierPriceRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository


CUSTOMER_PREFERENCE_FAMILY = {
    *PREFERENCE_FACT_FIELDS.keys(),
    COMMERCIAL_ACCEPTED_CURRENCY_KEY,
}
CUSTOMER_QUOTE_ACCEPTANCE_FAMILY = set(SUPPORTED_QUOTE_ACCEPTANCE_FACTS)
CUSTOMER_QUOTE_REASON_FAMILY = set(SUPPORTED_CUSTOMER_QUOTE_REASON_FACTS)
SUPPLIER_STRUCTURED_PREFIXES = (
    "response.",
    "commercial.",
    "contact.",
    "escalation.",
    "operation.",
)


def _has_pending_family(
    *,
    facts,
    subject_type: str,
    subject_id: str,
    exact_keys: set[str] | None = None,
    prefixes: tuple[str, ...] = (),
) -> bool:
    for item in facts:
        if (
            item.status != "proposed"
            or item.subject_type != subject_type
            or item.subject_id != subject_id
            or item.source_type != "minai_inference"
        ):
            continue
        if exact_keys is not None and item.fact_key in exact_keys:
            return True
        if prefixes and item.fact_key.startswith(prefixes):
            return True
    return False


def _proposal_count(result: dict[str, Any]) -> int:
    return (
        int(result.get("proposed_fact_count") or 0)
        + int(result.get("contextual_proposed_fact_count") or 0)
        + int(result.get("commercial_proposed_fact_count") or 0)
    )


def derive_review_safe_structured_learning(
    *,
    master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository,
    mina_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    supplier_price_repository: SupplierPriceRepository,
    quote_case_repository: QuoteCaseRepository,
    created_by: str = "MINAI Continuous Structured Learning",
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    current = occurred_at or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Structured learning timestamp must be timezone-aware.")
    current = current.astimezone(timezone.utc)

    facts = learning_repository.list_all()
    supplier_runs = supplier_skipped = supplier_proposals = 0
    customer_runs = customer_skipped = customer_proposals = 0
    errors: list[dict[str, str]] = []

    for supplier in master_repository.list_suppliers():
        if _has_pending_family(
            facts=facts,
            subject_type="supplier",
            subject_id=supplier.supplier_id,
            prefixes=SUPPLIER_STRUCTURED_PREFIXES,
        ):
            supplier_skipped += 1
            continue
        try:
            result = derive_supplier_history_learning(
                supplier_id=supplier.supplier_id,
                master_repository=master_repository,
                supplier_repository=supplier_repository,
                learning_repository=learning_repository,
                price_repository=supplier_price_repository,
                quote_case_repository=quote_case_repository,
                created_by=created_by,
                occurred_at=current,
            )
            supplier_runs += 1
            supplier_proposals += (
                len(result.get("proposed_facts") or [])
                + int(result.get("contextual_proposed_fact_count") or 0)
                + int(
                    (result.get("outcome_learning") or {}).get(
                        "proposed_fact_count", 0
                    )
                    or 0
                )
                + int(
                    (result.get("outcome_learning") or {}).get(
                        "contextual_proposed_fact_count", 0
                    )
                    or 0
                )
                + int(
                    (result.get("outcome_learning") or {}).get(
                        "customer_contextual_proposed_fact_count", 0
                    )
                    or 0
                )
            )
        except Exception as exc:
            errors.append(
                {
                    "subject_type": "supplier",
                    "subject_id": supplier.supplier_id,
                    "error_code": str(
                        getattr(exc, "code", None) or type(exc).__name__
                    ),
                }
            )

    # Refresh after supplier derivation so new supplier proposals cannot affect
    # customer-family gating and vice versa through stale snapshots.
    facts = learning_repository.list_all()
    for customer in master_repository.list_customers():
        family_specs = (
            (
                "preference",
                CUSTOMER_PREFERENCE_FAMILY,
                derive_customer_preference_learning,
            ),
            (
                "quote_acceptance",
                CUSTOMER_QUOTE_ACCEPTANCE_FAMILY,
                derive_customer_quote_acceptance_learning,
            ),
            (
                "quote_reason",
                CUSTOMER_QUOTE_REASON_FAMILY,
                derive_customer_quote_reason_learning,
            ),
        )
        for family_name, keys, derivation in family_specs:
            if _has_pending_family(
                facts=facts,
                subject_type="customer",
                subject_id=customer.customer_id,
                exact_keys=keys,
            ):
                customer_skipped += 1
                continue
            try:
                if family_name == "preference":
                    result = derivation(
                        customer_id=customer.customer_id,
                        master_repository=master_repository,
                        mina_repository=mina_repository,
                        learning_repository=learning_repository,
                        quote_case_repository=quote_case_repository,
                        created_by=created_by,
                        occurred_at=current,
                    )
                else:
                    result = derivation(
                        customer_id=customer.customer_id,
                        master_repository=master_repository,
                        mina_repository=mina_repository,
                        quote_case_repository=quote_case_repository,
                        learning_repository=learning_repository,
                        created_by=created_by,
                        occurred_at=current,
                    )
                customer_runs += 1
                customer_proposals += _proposal_count(result)
                facts = learning_repository.list_all()
            except Exception as exc:
                errors.append(
                    {
                        "subject_type": "customer",
                        "subject_id": customer.customer_id,
                        "family": family_name,
                        "error_code": str(
                            getattr(exc, "code", None) or type(exc).__name__
                        ),
                    }
                )

    return {
        "supplier_derivation_run_count": supplier_runs,
        "supplier_pending_skip_count": supplier_skipped,
        "supplier_proposed_fact_count": supplier_proposals,
        "customer_derivation_run_count": customer_runs,
        "customer_pending_skip_count": customer_skipped,
        "customer_proposed_fact_count": customer_proposals,
        "error_count": len(errors),
        "errors": errors[:50],
        "authority_created": False,
        "note": (
            "Existing structured learning services were invoked automatically. "
            "All newly derived facts remain proposed and require the existing "
            "human review lifecycle before any runtime authority."
        ),
    }
