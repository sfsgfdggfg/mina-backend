from __future__ import annotations

from unittest.mock import patch

from src.core.customer_memory import (
    CustomerMemoryProfile,
    enrich_shipment_with_customer_memory,
)
from src.core.models import Shipment


def evaluate_customer_identity_trust_regressions() -> dict:
    trusted_profile = CustomerMemoryProfile(
        customer_name="Acme Lojistik",
        aliases=["Acme"],
        trusted_sender_addresses=["ops@acme.test"],
        trusted_sender_domains=["acme.test"],
        default_pickup_city="Adana",
        default_pickup_country="Türkiye",
        operational_notes=["Trusted profile note."],
    )

    def profile_lookup(name):
        if (name or "").strip().lower() in {"acme lojistik", "acme"}:
            return trusted_profile
        return None

    shipment = Shipment(customer_name="Unrelated Company")
    with patch("src.core.customer_memory.find_customer_profile", return_value=None):
        result = enrich_shipment_with_customer_memory(
            shipment,
            email_text="Forwarded message from Acme Lojistik",
            sender_address="someone@other.test",
        )
    assert result.matched is False
    assert shipment.pickup_city is None

    shipment = Shipment(customer_name="Acme Lojistik")
    with patch("src.core.customer_memory.find_customer_profile", side_effect=profile_lookup):
        result = enrich_shipment_with_customer_memory(
            shipment,
            sender_address="unknown@other.test",
        )
    assert result.matched is False
    assert result.identity_status == "sender_verification_required"
    assert result.candidate_profile is not None
    assert shipment.pickup_city is None

    shipment = Shipment(customer_name="Acme Lojistik")
    with patch("src.core.customer_memory.find_customer_profile", side_effect=profile_lookup):
        result = enrich_shipment_with_customer_memory(
            shipment,
            sender_address="ops@acme.test",
        )
    assert result.matched is True
    assert result.identity_status == "trusted_sender"
    assert shipment.pickup_city == "Adana"

    shipment = Shipment(customer_name="Acme Lojistik")
    with patch("src.core.customer_memory.find_customer_profile", side_effect=profile_lookup):
        result = enrich_shipment_with_customer_memory(
            shipment,
            sender_address="new.person@acme.test",
        )
    assert result.matched is True

    shipment = Shipment(customer_name="Acme Lojistik")
    with patch("src.core.customer_memory.find_customer_profile", side_effect=profile_lookup):
        result = enrich_shipment_with_customer_memory(shipment)
    assert result.matched is False
    assert result.identity_status == "sender_verification_required"

    return {
        "name": "customer_identity_trust_regressions",
        "passed": True,
        "details": "5 identity-safety scenarios passed",
    }
