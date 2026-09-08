from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

OUTBOUND_MODE_ENV = "MINAI_OUTBOUND_MODE"
OutboundRuntimeMode = Literal["shadow", "controlled_send"]


class OutboundRuntimePolicy(BaseModel):
    mode: OutboundRuntimeMode = "shadow"
    source: str = "outbound_runtime_policy"

    @property
    def delivery_enabled(self) -> bool:
        return self.mode == "controlled_send"


def resolve_outbound_runtime_policy(
    environ: Mapping[str, str] | None = None,
) -> OutboundRuntimePolicy:
    env = environ if environ is not None else os.environ
    raw = (env.get(OUTBOUND_MODE_ENV) or "shadow").strip().casefold()
    if raw not in {"shadow", "controlled_send"}:
        raise ValueError(
            "MINAI_OUTBOUND_MODE must be 'shadow' or 'controlled_send'."
        )
    return OutboundRuntimePolicy(mode=raw)
