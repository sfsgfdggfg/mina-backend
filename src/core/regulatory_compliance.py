from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Mapping, TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.clarification_requirements import (
    ClarificationRequirement,
    get_commodity_clarification_requirements,
)

if TYPE_CHECKING:
    from src.core.models import Shipment


RegulatoryExceptionReviewStatus = Literal[
    "pending",
    "approved",
    "rejected",
]
RegulatoryComplianceStatus = Literal[
    "clear",
    "clarification_required",
    "blocked",
    "human_review_required",
]


class RegulatoryComplianceError(ValueError):
    pass


class RegulatoryExceptionTransitionError(RegulatoryComplianceError):
    pass


class RegulatoryExceptionReview(BaseModel):
    requirement_key: str
    customer_statement: str
    status: RegulatoryExceptionReviewStatus = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    source: str = "regulatory_compliance_engine"

    @field_validator("requirement_key", "customer_statement")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Regulatory review text must not be empty.")
        return normalized

    @model_validator(mode="after")
    def validate_review_state(self):
        if self.status == "pending":
            if any(
                value is not None
                for value in [
                    self.decided_by,
                    self.decided_at,
                    self.decision_reason,
                ]
            ):
                raise ValueError(
                    "Pending regulatory review must not include decision metadata."
                )
            return self

        if not self.decided_by or self.decided_at is None:
            raise ValueError(
                "Decided regulatory review requires decided_by and decided_at."
            )

        if self.status == "rejected" and not self.decision_reason:
            raise ValueError(
                "Rejected regulatory review requires decision_reason."
            )

        return self


class RegulatoryComplianceAssessment(BaseModel):
    status: RegulatoryComplianceStatus
    can_continue_to_quote: bool
    requires_human_review: bool
    unknown_requirements: list[str] = Field(default_factory=list)
    blocking_requirements: list[str] = Field(default_factory=list)
    pending_review_requirements: list[str] = Field(default_factory=list)
    approved_exception_requirements: list[str] = Field(
        default_factory=list
    )
    reasons: list[str] = Field(default_factory=list)
    source: str = "regulatory_compliance_engine"


def _regulatory_requirements(
    commodity: str | None,
) -> list[ClarificationRequirement]:
    return [
        requirement
        for requirement in get_commodity_clarification_requirements(
            commodity
        )
        if requirement.compliance_policy is not None
        and requirement.compliance_policy.required_before_quote
    ]


def _get_reviewable_requirement(
    shipment: "Shipment",
    requirement_key: str,
) -> ClarificationRequirement:
    requirement = next(
        (
            item
            for item in _regulatory_requirements(shipment.commodity)
            if item.key == requirement_key
        ),
        None,
    )

    if (
        requirement is None
        or requirement.compliance_policy is None
        or not requirement.compliance_policy.customer_promise_requires_human_review
    ):
        raise RegulatoryComplianceError(
            f"Requirement '{requirement_key}' does not support a "
            "regulatory exception review for this commodity."
        )

    return requirement


def validate_regulatory_exception_reviews(
    commodity: str | None,
    commodity_attributes: Mapping[str, object],
    reviews: Mapping[str, RegulatoryExceptionReview],
) -> None:
    reviewable_keys = {
        requirement.key
        for requirement in _regulatory_requirements(commodity)
        if requirement.compliance_policy is not None
        and requirement.compliance_policy.customer_promise_requires_human_review
    }

    for key, review in reviews.items():
        if key != review.requirement_key:
            raise RegulatoryComplianceError(
                "Regulatory exception review map key must match "
                "requirement_key."
            )

        if key not in reviewable_keys:
            raise RegulatoryComplianceError(
                f"Requirement '{key}' is not reviewable for commodity "
                f"'{commodity}'."
            )

        if commodity_attributes.get(key) is not False:
            raise RegulatoryComplianceError(
                f"Regulatory exception review for '{key}' requires an "
                "explicit unavailable document answer."
            )


def request_regulatory_exception_review(
    shipment: "Shipment",
    requirement_key: str,
    customer_statement: str,
) -> "Shipment":
    _get_reviewable_requirement(shipment, requirement_key)

    if shipment.commodity_attributes.get(requirement_key) is not False:
        raise RegulatoryComplianceError(
            "A customer promise can be reviewed only after the document "
            "has been explicitly marked unavailable."
        )

    if requirement_key in shipment.regulatory_exception_reviews:
        raise RegulatoryExceptionTransitionError(
            f"Regulatory exception review already exists for "
            f"'{requirement_key}'."
        )

    review = RegulatoryExceptionReview(
        requirement_key=requirement_key,
        customer_statement=customer_statement,
    )
    updated = shipment.model_copy(deep=True)
    updated.regulatory_exception_reviews[requirement_key] = review
    return shipment.__class__.model_validate(updated.model_dump())


def approve_regulatory_exception(
    shipment: "Shipment",
    requirement_key: str,
    decided_by: str,
    decision_reason: str | None = None,
    decided_at: datetime | None = None,
) -> "Shipment":
    review = shipment.regulatory_exception_reviews.get(requirement_key)

    if review is None or review.status != "pending":
        raise RegulatoryExceptionTransitionError(
            "Only a pending regulatory exception can be approved."
        )

    normalized_decided_by = decided_by.strip()
    if not normalized_decided_by:
        raise ValueError("decided_by must not be empty.")

    normalized_reason = (
        decision_reason.strip() if decision_reason else None
    )
    approved = RegulatoryExceptionReview.model_validate(
        review.model_copy(
            update={
                "status": "approved",
                "decided_by": normalized_decided_by,
                "decided_at": decided_at or datetime.now(timezone.utc),
                "decision_reason": normalized_reason,
            }
        ).model_dump()
    )
    updated = shipment.model_copy(deep=True)
    updated.regulatory_exception_reviews[requirement_key] = approved
    return shipment.__class__.model_validate(updated.model_dump())


def reject_regulatory_exception(
    shipment: "Shipment",
    requirement_key: str,
    decided_by: str,
    decision_reason: str,
    decided_at: datetime | None = None,
) -> "Shipment":
    review = shipment.regulatory_exception_reviews.get(requirement_key)

    if review is None or review.status != "pending":
        raise RegulatoryExceptionTransitionError(
            "Only a pending regulatory exception can be rejected."
        )

    normalized_decided_by = decided_by.strip()
    normalized_reason = decision_reason.strip()
    if not normalized_decided_by:
        raise ValueError("decided_by must not be empty.")
    if not normalized_reason:
        raise ValueError("decision_reason must not be empty.")

    rejected = RegulatoryExceptionReview.model_validate(
        review.model_copy(
            update={
                "status": "rejected",
                "decided_by": normalized_decided_by,
                "decided_at": decided_at or datetime.now(timezone.utc),
                "decision_reason": normalized_reason,
            }
        ).model_dump()
    )
    updated = shipment.model_copy(deep=True)
    updated.regulatory_exception_reviews[requirement_key] = rejected
    return shipment.__class__.model_validate(updated.model_dump())


def assess_regulatory_compliance(
    shipment: "Shipment",
) -> RegulatoryComplianceAssessment:
    unknown: list[str] = []
    blocking: list[str] = []
    pending: list[str] = []
    approved: list[str] = []
    reasons: list[str] = []

    for requirement in _regulatory_requirements(shipment.commodity):
        policy = requirement.compliance_policy
        if policy is None:
            continue

        label = policy.document_label

        if requirement.key not in shipment.commodity_attributes:
            unknown.append(requirement.key)
            reasons.append(
                f"{label} için belge durumu henüz bilinmiyor."
            )
            continue

        if shipment.commodity_attributes[requirement.key] is True:
            continue

        review = shipment.regulatory_exception_reviews.get(
            requirement.key
        )

        if review is None:
            blocking.append(requirement.key)
            reasons.append(
                f"{label} mevcut değil. Zorunlu düzenleyici belge "
                "sağlanmadan otomatik teklif oluşturulamaz."
            )
        elif review.status == "pending":
            pending.append(requirement.key)
            reasons.append(
                f"{label} şu anda mevcut değil ve müşteri belgeyi "
                "daha sonra sağlayacağını belirtti. Tekliften önce "
                "açık insan onayı gerekiyor."
            )
        elif review.status == "rejected":
            blocking.append(requirement.key)
            reasons.append(
                f"{label} için daha sonra sağlama istisnası insan "
                "incelemesinde reddedildi: "
                f"{review.decision_reason}"
            )
        else:
            approved.append(requirement.key)

    if blocking:
        status: RegulatoryComplianceStatus = "blocked"
    elif pending:
        status = "human_review_required"
    elif unknown:
        status = "clarification_required"
    else:
        status = "clear"

    return RegulatoryComplianceAssessment(
        status=status,
        can_continue_to_quote=status == "clear",
        requires_human_review=status == "human_review_required",
        unknown_requirements=unknown,
        blocking_requirements=blocking,
        pending_review_requirements=pending,
        approved_exception_requirements=approved,
        reasons=reasons,
    )
