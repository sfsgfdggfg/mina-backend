from __future__ import annotations

ADR_CAPABILITY = "adr"
ADR_CLASS_1_CAPABILITY = "class_1"
ADR_CLASS_7_CAPABILITY = "class_7"

REEFER_CAPABILITY = "reefer"
TEMPERATURE_CONTROLLED_CAPABILITY = "temperature_controlled"
COLD_CHAIN_CAPABILITY = "cold_chain"

LTL_CAPABILITY = "ltl"
PARTIAL_CAPABILITY = "partial"
PARSIYEL_CAPABILITY = "parsiyel"

ALLOWED_SPECIAL_CAPABILITIES = {
    ADR_CAPABILITY,
    ADR_CLASS_1_CAPABILITY,
    ADR_CLASS_7_CAPABILITY,
    REEFER_CAPABILITY,
    TEMPERATURE_CONTROLLED_CAPABILITY,
    COLD_CHAIN_CAPABILITY,
    LTL_CAPABILITY,
    PARTIAL_CAPABILITY,
    PARSIYEL_CAPABILITY,
}

ADR_CLASS_CAPABILITY_MAP = {
    "1": ADR_CLASS_1_CAPABILITY,
    "7": ADR_CLASS_7_CAPABILITY,
}


def get_required_adr_class_capability(adr_class: str | None) -> str | None:
    if adr_class is None:
        return None

    return ADR_CLASS_CAPABILITY_MAP.get(str(adr_class).strip())
