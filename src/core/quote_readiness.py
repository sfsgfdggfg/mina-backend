from __future__ import annotations

from pydantic import BaseModel
from typing import List

from src.core.missing_info import MissingInfoResult
from src.core.models import RiskAssessment


class QuoteReadinessDecision(BaseModel):
    result_type: str
    can_generate_quote: bool
    requires_human_review: bool
    reasons: List[str] = []
    source: str = "quote_readiness_engine"


def decide_quote_readiness(
    *,
    missing_info: MissingInfoResult,
    risk_assessment: RiskAssessment,
    operational_consistency: dict,
) -> QuoteReadinessDecision:
    errors = operational_consistency.get("errors", []) or []

    if risk_assessment.risk_level == "red":
        return QuoteReadinessDecision(
            result_type="management_review",
            can_generate_quote=False,
            requires_human_review=True,
            reasons=list(risk_assessment.risk_reasons),
        )

    if not missing_info.can_continue_to_quote:
        return QuoteReadinessDecision(
            result_type="clarification",
            can_generate_quote=False,
            requires_human_review=True,
            reasons=list(missing_info.missing_fields),
        )

    if errors:
        return QuoteReadinessDecision(
            result_type="blocked",
            can_generate_quote=False,
            requires_human_review=True,
            reasons=list(errors),
        )

    if risk_assessment.risk_level == "yellow":
        return QuoteReadinessDecision(
            result_type="quote_with_review",
            can_generate_quote=True,
            requires_human_review=True,
            reasons=list(risk_assessment.risk_reasons),
        )

    return QuoteReadinessDecision(
        result_type="quote_ready",
        can_generate_quote=True,
        requires_human_review=False,
        reasons=[],
    )
