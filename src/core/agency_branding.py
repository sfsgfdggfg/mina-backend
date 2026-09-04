from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_LOGO_BYTES = 256 * 1024
MAX_LOGO_DATA_URI_LENGTH = 360_000
SUPPORTED_LOGO_MIME = {"image/png", "image/jpeg", "image/webp"}


class AgencyBrandingUpdate(BaseModel):
    company_name: str = Field(min_length=1, max_length=120)
    logo_data_uri: str | None = Field(default=None, max_length=MAX_LOGO_DATA_URI_LENGTH)
    primary_color: str = "#3157D5"
    secondary_accent_color: str = "#172033"

    @field_validator("company_name")
    @classmethod
    def clean_company_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Company name is required.")
        return cleaned
    @field_validator("primary_color", "secondary_accent_color")
    @classmethod
    def validate_hex_color(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not HEX_COLOR_RE.fullmatch(normalized):
            raise ValueError("Brand colors must use #RRGGBB format.")
        return normalized

    @field_validator("logo_data_uri")
    @classmethod
    def validate_logo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("data:") or ";base64," not in value:
            raise ValueError("Logo must be an embedded image data URI.")
        header, encoded = value.split(",", 1)
        mime = header[5:].split(";", 1)[0].lower()
        if mime not in SUPPORTED_LOGO_MIME:
            raise ValueError("Logo must be PNG, JPEG, or WebP.")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Logo image data is invalid.") from exc
        if not raw or len(raw) > MAX_LOGO_BYTES:
            raise ValueError("Logo must be between 1 byte and 256 KB.")
        _validate_image_magic(mime, raw)
        return f"data:{mime};base64,{encoded}"


class AgencyBrandingSettings(AgencyBrandingUpdate):
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)
    source: str = "agency_branding_settings"

    @model_validator(mode="after")
    def validate_timestamp(self):
        if self.updated_at.tzinfo is None:
            raise ValueError("Branding timestamp must be timezone-aware.")
        return self


def default_branding_settings() -> AgencyBrandingSettings:
    return AgencyBrandingSettings(
        company_name="MINAI",
        logo_data_uri=None,
        primary_color="#3157D5",
        secondary_accent_color="#172033",
        updated_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
        updated_by="system_default",
    )


def _validate_image_magic(mime: str, raw: bytes) -> None:
    valid = False
    if mime == "image/png":
        valid = raw.startswith(b"\x89PNG\r\n\x1a\n")
    elif mime == "image/jpeg":
        valid = raw.startswith(b"\xff\xd8\xff")
    elif mime == "image/webp":
        valid = len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    if not valid:
        raise ValueError("Logo bytes do not match the declared image type.")


def _rgb(color: str) -> tuple[int, int, int]:
    return tuple(int(color[index:index + 2], 16) for index in (1, 3, 5))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, part)):02X}" for part in rgb)


def _mix(color: str, target: str, target_weight: float) -> str:
    source_rgb, target_rgb = _rgb(color), _rgb(target)
    mixed = tuple(round(a * (1 - target_weight) + b * target_weight) for a, b in zip(source_rgb, target_rgb))
    return _hex(mixed)


def _relative_luminance(color: str) -> float:
    values = []
    for channel in _rgb(color):
        normalized = channel / 255
        values.append(normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4)
    red, green, blue = values
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(left: str, right: str) -> float:
    high, low = sorted((_relative_luminance(left), _relative_luminance(right)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def contrast_text_color(background: str) -> str:
    candidates = ("#FFFFFF", "#172033")
    return max(candidates, key=lambda candidate: _contrast_ratio(background, candidate))


def branding_public_payload(settings: AgencyBrandingSettings) -> dict[str, Any]:
    primary = settings.primary_color
    secondary = settings.secondary_accent_color
    return {
        "company_name": settings.company_name,
        "logo_data_uri": settings.logo_data_uri,
        "primary_color": primary,
        "primary_contrast_color": contrast_text_color(primary),
        "primary_soft_color": _mix(primary, "#FFFFFF", 0.90),
        "primary_hover_color": _mix(primary, "#000000", 0.12),
        "secondary_accent_color": secondary,
        "secondary_contrast_color": contrast_text_color(secondary),
        "secondary_soft_color": _mix(secondary, "#FFFFFF", 0.90),
        "secondary_hover_color": _mix(secondary, "#000000", 0.12),
        "updated_at": settings.updated_at,
        "updated_by": settings.updated_by,
        "critical_status_colors_locked": True,
    }
