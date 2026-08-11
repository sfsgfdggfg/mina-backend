from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.models import Shipment


HEAVY_SINGLE_PIECE_THRESHOLD_KG = 26000.0


@dataclass(frozen=True)
class CargoWeightAssessment:
    confirmed_single_piece_weight_kg: Optional[float] = None
    requires_clarification: bool = False
    clarification_reason: Optional[str] = None

    @property
    def is_confirmed_heavy_single_piece(self) -> bool:
        return (
            self.confirmed_single_piece_weight_kg is not None
            and self.confirmed_single_piece_weight_kg
            >= HEAVY_SINGLE_PIECE_THRESHOLD_KG
        )


def assess_cargo_weight(shipment: Shipment) -> CargoWeightAssessment:
    """Interpret weight fields without treating an ambiguous line total as per-piece.

    Shipment.gross_weight_kg is the total gross shipment weight. A package-line
    weight is a confirmed single-piece weight only when that line has quantity 1.
    If the shipment contains exactly one piece, gross weight is also a safe
    single-piece value. For quantity greater than 1, package weight may be either
    per-piece or line-total in the current input contract, so a threshold-crossing
    value requires clarification.
    """

    confirmed_single_piece_weights: list[float] = []
    ambiguous_heavy_package_line = False
    total_piece_count = 0

    for package in shipment.packages:
        quantity = package.quantity

        if quantity > 0:
            total_piece_count += quantity

        if package.weight_kg is None:
            continue

        if quantity == 1:
            confirmed_single_piece_weights.append(package.weight_kg)
        elif (
            quantity > 1
            and package.weight_kg >= HEAVY_SINGLE_PIECE_THRESHOLD_KG
        ):
            ambiguous_heavy_package_line = True

    if (
        total_piece_count == 1
        and shipment.gross_weight_kg is not None
    ):
        confirmed_single_piece_weights.append(shipment.gross_weight_kg)

    confirmed_heavy_weights = [
        weight
        for weight in confirmed_single_piece_weights
        if weight >= HEAVY_SINGLE_PIECE_THRESHOLD_KG
    ]

    if confirmed_heavy_weights:
        return CargoWeightAssessment(
            confirmed_single_piece_weight_kg=max(confirmed_heavy_weights)
        )

    if ambiguous_heavy_package_line:
        return CargoWeightAssessment(
            requires_clarification=True,
            clarification_reason=(
                "Package-line weight reaches the heavy-cargo threshold, but "
                "quantity is greater than one and the value may be either "
                "per-piece or line-total."
            ),
        )

    if (
        not shipment.packages
        and shipment.gross_weight_kg is not None
        and shipment.gross_weight_kg >= HEAVY_SINGLE_PIECE_THRESHOLD_KG
    ):
        return CargoWeightAssessment(
            requires_clarification=True,
            clarification_reason=(
                "Shipment gross weight reaches the heavy-cargo threshold, "
                "but package count and per-piece weights are missing."
            ),
        )

    return CargoWeightAssessment()
