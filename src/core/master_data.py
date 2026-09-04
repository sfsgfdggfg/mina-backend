from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator
from src.core.pricing_policy import PricingFormula


SupplierRole = Literal["primary", "backup", "specialist"]
GeographyScopeType = Literal["country", "region"]
GeographyStrength = Literal["main_market", "strong", "works", "limited"]
MasterDataSource = Literal["manual", "legacy_json", "excel_import"]
ContactRole = Literal[
    "pricing", "operations", "finance", "decision_maker", "management", "other"
]

GEOGRAPHY_STRENGTH_SCORE = {
    "main_market": 1.0,
    "strong": 0.85,
    "works": 0.65,
    "limited": 0.35,
}


def normalize_master_text(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def normalize_country(value: str) -> str:
    aliases = {
        "türkiye": "turkiye", "turkey": "turkiye", "tr": "turkiye",
        "almanya": "germany", "deutschland": "germany", "de": "germany",
        "avusturya": "austria", "österreich": "austria", "at": "austria",
        "isviçre": "switzerland", "isvicre": "switzerland", "ch": "switzerland",
        "belçika": "belgium", "belcika": "belgium", "be": "belgium",
        "hollanda": "netherlands", "the netherlands": "netherlands", "nl": "netherlands",
        "fransa": "france", "fr": "france", "italya": "italy", "it": "italy",
        "romanya": "romania", "ro": "romania", "bulgaristan": "bulgaria", "bg": "bulgaria",
        "polonya": "poland", "pl": "poland", "çekya": "czechia", "cekya": "czechia",
        "danimarka": "denmark", "dk": "denmark", "isveç": "sweden", "isvec": "sweden",
        "norveç": "norway", "norvec": "norway", "finlandiya": "finland",
        "lüksemburg": "luxembourg", "lüksenburg": "luxembourg", "luksemburg": "luxembourg", "luxembourg": "luxembourg",
    }
    normalized = normalize_master_text(value).replace("\u0307", "")
    return aliases.get(normalized, normalized)


class MasterContact(BaseModel):
    contact_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=80)
    roles: list[ContactRole] = Field(default_factory=list)
    is_primary: bool = False
    active: bool = True

    @field_validator("email", "phone", "contact_name", mode="before")
    @classmethod
    def clean_optional_contact_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def require_channel(self):
        if not (self.email or self.phone):
            raise ValueError("Master contact requires email or phone.")
        if self.email is not None:
            if self.email.count("@") != 1 or any(ch.isspace() for ch in self.email):
                raise ValueError("Master contact email must be a valid bounded email address.")
            self.email = self.email.casefold()
        self.roles = list(dict.fromkeys(self.roles))
        return self


class SupplierGeographyCapability(BaseModel):
    scope_type: GeographyScopeType
    scope_name: str = Field(min_length=1, max_length=120)
    countries: list[str] = Field(default_factory=list)
    strength: GeographyStrength = "works"
    source: MasterDataSource = "manual"
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("scope_name", mode="before")
    @classmethod
    def clean_scope_name(cls, value):
        return str(value).strip()

    @field_validator("countries", mode="before")
    @classmethod
    def normalize_countries(cls, value):
        if value is None:
            return []
        cleaned = []
        for item in value:
            normalized = normalize_country(str(item))
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type == "country":
            country = normalize_country(self.scope_name)
            self.countries = [country]
        elif not self.countries:
            raise ValueError("Region geography requires explicit countries for deterministic matching.")
        return self


class CustomerMasterProfile(BaseModel):
    customer_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    customer_name: str = Field(min_length=1, max_length=240)
    active: bool = True
    aliases: list[str] = Field(default_factory=list)
    trusted_sender_addresses: list[str] = Field(default_factory=list)
    trusted_sender_domains: list[str] = Field(default_factory=list)
    contacts: list[MasterContact] = Field(default_factory=list)
    sales_owner: str | None = Field(default=None, max_length=200)
    default_commodity: str | None = Field(default=None, max_length=300)
    default_equipment_type: str | None = Field(default=None, max_length=300)
    default_pickup_city: str | None = Field(default=None, max_length=200)
    default_pickup_area: str | None = Field(default=None, max_length=300)
    default_pickup_country: str | None = Field(default=None, max_length=120)
    default_delivery_city: str | None = Field(default=None, max_length=200)
    default_delivery_country: str | None = Field(default=None, max_length=120)
    price_sensitivity: str | None = Field(default=None, max_length=80)
    time_sensitivity: str | None = Field(default=None, max_length=80)
    pricing_policy: PricingFormula | None = None
    operational_notes: list[str] = Field(default_factory=list)
    source: MasterDataSource = "manual"
    created_at: datetime
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_times(self):
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Master-data timestamps must be timezone-aware.")
        if self.updated_at < self.created_at:
            raise ValueError("Master-data updated_at cannot precede created_at.")
        return self


class SupplierMasterProfile(BaseModel):
    supplier_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    supplier_name: str = Field(min_length=1, max_length=240)
    active: bool = True
    role: SupplierRole = "backup"
    contacts: list[MasterContact] = Field(default_factory=list)
    geographies: list[SupplierGeographyCapability] = Field(default_factory=list)
    service_types: list[str] = Field(default_factory=list)
    equipment_types: list[str] = Field(default_factory=list)
    special_capabilities: list[str] = Field(default_factory=list)
    priority_routes: list[str] = Field(default_factory=list)
    legacy_region_tags: list[str] = Field(default_factory=list)
    reliability_score: float = Field(default=0.5, ge=0, le=1)
    price_score: float = Field(default=0.5, ge=0, le=1)
    speed_score: float = Field(default=0.5, ge=0, le=1)
    notes: str = Field(default="Master supplier profile.", min_length=1, max_length=2000)
    source: MasterDataSource = "manual"
    created_at: datetime
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_times(self):
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Master-data timestamps must be timezone-aware.")
        if self.updated_at < self.created_at:
            raise ValueError("Master-data updated_at cannot precede created_at.")
        active_primary = [contact for contact in self.contacts if contact.active and contact.is_primary]
        if len(active_primary) > 1:
            raise ValueError("Supplier master allows only one active primary contact.")
        seen_geo = set()
        for geography in self.geographies:
            key = (geography.scope_type, normalize_master_text(geography.scope_name))
            if key in seen_geo:
                raise ValueError("Supplier master contains duplicate geography scope.")
            seen_geo.add(key)
        return self


class SupplierGeographyMatch(BaseModel):
    matched: bool
    destination_country: str
    best_strength: GeographyStrength | None = None
    strength_score: float = 0.0
    matched_scope_type: GeographyScopeType | None = None
    matched_scope_name: str | None = None
    source: str = "supplier_master_geography"


def match_supplier_geography(
    profile: SupplierMasterProfile, destination_country: str
) -> SupplierGeographyMatch:
    target = normalize_country(destination_country)
    matches = [geo for geo in profile.geographies if target in geo.countries]
    if not matches:
        return SupplierGeographyMatch(matched=False, destination_country=target)
    best = max(matches, key=lambda item: GEOGRAPHY_STRENGTH_SCORE[item.strength])
    return SupplierGeographyMatch(
        matched=True,
        destination_country=target,
        best_strength=best.strength,
        strength_score=GEOGRAPHY_STRENGTH_SCORE[best.strength],
        matched_scope_type=best.scope_type,
        matched_scope_name=best.scope_name,
    )
