from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional


HS_COMMODITY_MAP_PATH = Path("data/hs_commodity_map.json")


def normalize_gtip_code(raw_code: Optional[str]) -> Optional[str]:
    """
    Normalize GTIP / HS codes by keeping only digits.

    Examples:
    - 2202.10.00.00.00 -> 220210000000
    - 8504 21 00 00 00 -> 850421000000

    MINAI does not assign legally binding GTIP codes.
    It only interprets customer-provided codes for operational classification.
    """

    if not raw_code:
        return None

    digits = re.sub(r"\D", "", raw_code)

    if len(digits) < 2:
        return None

    if len(digits) > 12:
        digits = digits[:12]

    return digits


def split_gtip_code(gtip_code: Optional[str]) -> Dict[str, Optional[str]]:
    normalized_code = normalize_gtip_code(gtip_code)

    if not normalized_code:
        return {
            "gtip_code": None,
            "hs_chapter": None,
            "hs_heading": None,
            "hs_subheading": None,
        }

    return {
        "gtip_code": normalized_code,
        "hs_chapter": normalized_code[:2] if len(normalized_code) >= 2 else None,
        "hs_heading": normalized_code[:4] if len(normalized_code) >= 4 else None,
        "hs_subheading": normalized_code[:6] if len(normalized_code) >= 6 else None,
    }


def extract_gtip_code_from_text(email_text: str) -> Optional[str]:
    """
    Extract a customer-provided GTIP / HS code from raw email text.

    This function is intentionally conservative:
    it looks for explicit GTIP / HS labels before extracting a code.
    """

    text = email_text or ""

    label_pattern = re.compile(
        r"(?i)(gt[iıİI]p|g\.t\.i\.p|hs\s*code|hs\s*kod|tarife\s*kodu|gumruk\s*tarife\s*kodu|gümrük\s*tarife\s*kodu)"
        r"[^0-9]{0,30}"
        r"([0-9][0-9.\s/-]{1,30})"
    )

    match = label_pattern.search(text)

    if not match:
        return None

    return normalize_gtip_code(match.group(2))


def load_hs_commodity_map() -> Dict[str, Dict[str, Any]]:
    if not HS_COMMODITY_MAP_PATH.exists():
        return {}

    try:
        raw_data = json.loads(HS_COMMODITY_MAP_PATH.read_text())
    except json.JSONDecodeError:
        return {}

    if not isinstance(raw_data, dict):
        return {}

    return {
        str(key): value
        for key, value in raw_data.items()
        if isinstance(value, dict)
    }


def map_gtip_to_commodity(gtip_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Map GTIP / HS code to operational commodity data.

    Matching priority:
    1. HS heading, e.g. 8504
    2. HS chapter, e.g. 85
    """

    parts = split_gtip_code(gtip_code)
    hs_map = load_hs_commodity_map()

    for key in [parts["hs_heading"], parts["hs_chapter"]]:
        if key and key in hs_map:
            result = dict(hs_map[key])
            result["matched_hs_key"] = key
            result["source"] = str(HS_COMMODITY_MAP_PATH)
            return result

    return None


def interpret_gtip_from_email(email_text: str) -> Dict[str, Any]:
    detected_code = extract_gtip_code_from_text(email_text)
    parts = split_gtip_code(detected_code)
    commodity_match = map_gtip_to_commodity(detected_code)

    return {
        **parts,
        "gtip_detected_from_email": detected_code is not None,
        "commodity_match": commodity_match,
    }
