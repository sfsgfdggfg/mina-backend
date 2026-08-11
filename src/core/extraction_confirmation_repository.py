from __future__ import annotations

from typing import Optional, Protocol

from src.core.extraction_confirmation import ShipmentExtractionProposal


class ExtractionProposalRepository(Protocol):
    def save(
        self,
        proposal: ShipmentExtractionProposal,
    ) -> ShipmentExtractionProposal:
        ...

    def get(self, proposal_id: str) -> Optional[ShipmentExtractionProposal]:
        ...

    def list_all(self) -> list[ShipmentExtractionProposal]:
        ...


class InMemoryExtractionProposalRepository:
    def __init__(self) -> None:
        self._proposals: dict[str, ShipmentExtractionProposal] = {}

    def save(
        self,
        proposal: ShipmentExtractionProposal,
    ) -> ShipmentExtractionProposal:
        stored = proposal.model_copy(deep=True)
        self._proposals[proposal.proposal_id] = stored
        return stored.model_copy(deep=True)

    def get(self, proposal_id: str) -> Optional[ShipmentExtractionProposal]:
        proposal = self._proposals.get(proposal_id)
        return proposal.model_copy(deep=True) if proposal is not None else None

    def list_all(self) -> list[ShipmentExtractionProposal]:
        return [
            proposal.model_copy(deep=True)
            for proposal in self._proposals.values()
        ]
