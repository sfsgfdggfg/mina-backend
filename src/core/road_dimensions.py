from __future__ import annotations

from typing import Protocol


STANDARD_TRAILER_LENGTH_CM = 1360.0
STANDARD_TRAILER_WIDTH_CM = 250.0
PROJECT_CARGO_HEIGHT_CM = 300.0
MEGA_TRAILER_HEIGHT_TRIGGER_CM = 285.0


class PackageDimensions(Protocol):
    length_cm: float | None
    width_cm: float | None
    height_cm: float | None


def is_overlength(package: PackageDimensions) -> bool:
    return (
        package.length_cm is not None
        and package.length_cm > STANDARD_TRAILER_LENGTH_CM
    )


def is_overwidth(package: PackageDimensions) -> bool:
    return (
        package.width_cm is not None
        and package.width_cm > STANDARD_TRAILER_WIDTH_CM
    )


def requires_nonstandard_height_equipment(package: PackageDimensions) -> bool:
    return (
        package.height_cm is not None
        and package.height_cm > MEGA_TRAILER_HEIGHT_TRIGGER_CM
    )


def is_project_height(package: PackageDimensions) -> bool:
    return (
        package.height_cm is not None
        and package.height_cm > PROJECT_CARGO_HEIGHT_CM
    )


def requires_project_dimension_handling(package: PackageDimensions) -> bool:
    return is_overlength(package) or is_overwidth(package) or is_project_height(package)
