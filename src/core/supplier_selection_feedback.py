from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

SelectionFeedbackVerdict = Literal["agree", "disagree"]
SelectionFeedbackReason = Literal[
    "selection_looks_right",
    "relationship_context_missing",
    "route_fit_inaccurate",
    "equipment_fit_inaccurate",
    "price_expectation_inaccurate",
    "response_expectation_inaccurate",
    "temporary_supplier_issue",
    "other",
]


class SupplierSelectionFeedbackEvidence(BaseModel):
    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    mina_job_id: str = Field(min_length=1, max_length=200)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    workflow_id: str = Field(min_length=1, max_length=200)
    rfq_id: str = Field(min_length=1, max_length=200)
    supplier_name: str = Field(min_length=1, max_length=240)
    selection_priority: int = Field(ge=1, le=100)
    verdict: SelectionFeedbackVerdict
    reason_code: SelectionFeedbackReason
    note: str | None = Field(default=None, max_length=1200)
    selection_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    source: Literal["supplier_selection_feedback_v1"] = "supplier_selection_feedback_v1"

    @model_validator(mode="after")
    def validate_feedback_semantics(self):
        if self.recorded_at.tzinfo is None:
            raise ValueError("Supplier selection feedback timestamp must be timezone-aware.")
        if self.verdict == "agree" and self.reason_code != "selection_looks_right":
            raise ValueError("Agree feedback must use selection_looks_right reason.")
        if self.verdict == "disagree" and self.reason_code == "selection_looks_right":
            raise ValueError("Disagree feedback requires a structured disagreement reason.")
        if self.reason_code == "other" and not (self.note or "").strip():
            raise ValueError("Other selection feedback requires a note.")
        return self
