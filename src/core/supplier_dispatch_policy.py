from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, model_validator


AGENCY_SUPPLIER_DISPATCH_POLICY_ENV = "MINAI_SUPPLIER_DISPATCH_POLICY_JSON"

DispatchMode = Literal["sequential", "parallel"]


class SupplierDispatchPolicy(BaseModel):
    mode: DispatchMode = "sequential"
    initial_supplier_count: int = Field(default=1, ge=1, le=3)
    source: str = "agency_supplier_dispatch_policy"

    @model_validator(mode="after")
    def validate_mode_count(self):
        if self.mode == "sequential" and self.initial_supplier_count != 1:
            raise ValueError(
                "Sequential supplier dispatch requires initial_supplier_count=1."
            )
        if self.mode == "parallel" and self.initial_supplier_count < 2:
            raise ValueError(
                "Parallel supplier dispatch requires initial_supplier_count >= 2."
            )
        return self


def resolve_supplier_dispatch_policy(
    environ: Mapping[str, str] | None = None,
) -> SupplierDispatchPolicy:
    env = environ if environ is not None else os.environ
    raw = (env.get(AGENCY_SUPPLIER_DISPATCH_POLICY_ENV) or "").strip()
    if not raw:
        return SupplierDispatchPolicy()
    try:
        payload = json.loads(raw)
        return SupplierDispatchPolicy.model_validate(payload)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError(
            f"Agency supplier dispatch policy configuration is invalid: {exc}"
        ) from exc
