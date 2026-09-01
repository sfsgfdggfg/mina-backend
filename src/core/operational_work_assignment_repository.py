from __future__ import annotations

from typing import Protocol

from src.core.operational_work_assignment import OperationalWorkAssignment


class OperationalWorkAssignmentRepository(Protocol):
    def save(self, assignment: OperationalWorkAssignment) -> OperationalWorkAssignment: ...
    def get(self, work_id: str) -> OperationalWorkAssignment | None: ...
    def list_all(self) -> list[OperationalWorkAssignment]: ...


class InMemoryOperationalWorkAssignmentRepository:
    def __init__(self) -> None:
        self._assignments: dict[str, OperationalWorkAssignment] = {}

    def save(self, assignment: OperationalWorkAssignment) -> OperationalWorkAssignment:
        stored = assignment.model_copy(deep=True)
        self._assignments[assignment.work_id] = stored
        return stored.model_copy(deep=True)

    def get(self, work_id: str) -> OperationalWorkAssignment | None:
        assignment = self._assignments.get(work_id)
        return None if assignment is None else assignment.model_copy(deep=True)

    def list_all(self) -> list[OperationalWorkAssignment]:
        return [item.model_copy(deep=True) for item in self._assignments.values()]
