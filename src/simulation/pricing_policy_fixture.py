"""Explicit deterministic pricing config for offline regression scenarios only."""

SYNTHETIC_AGENCY_PRICING_POLICY_JSON = (
    '{"default_formula":{"method":"cost_markup_percentage","value":15},'
    '"default_rounding":{"mode":"none"},'
    '"currency_rounding":{"EUR":{"mode":"up","increment":10}}}'
)
