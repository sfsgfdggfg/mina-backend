from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Protocol

from src.core.mina_job import (
    MinaJob,
    MinaJobEvent,
    MinaJobIntakeChannel,
    MinaJobKind,
)
from src.core.models import Shipment


class MinaJobRepository(Protocol):
    def create_for_proposal(
        self,
        *,
        proposal_id: str,
        shipment: Shipment,
        opened_by: str,
        opened_at: datetime,
        sequence_year: int,
        lifecycle_version: int,
        job_kind: MinaJobKind,
        sales_owner: str | None = None,
        operations_owner: str | None = None,
    ) -> tuple[MinaJob, bool]: ...

    def create_manual(
        self,
        *,
        manual_intake_id: str,
        intake_channel: MinaJobIntakeChannel,
        job_kind: MinaJobKind,
        shipment: Shipment,
        opened_by: str,
        opened_at: datetime,
        sequence_year: int,
        lifecycle_version: int,
        sales_owner: str | None = None,
        operations_owner: str | None = None,
    ) -> tuple[MinaJob, bool]: ...

    def save(self, job: MinaJob) -> MinaJob: ...
    def get(self, job_id: str) -> MinaJob | None: ...
    def get_by_code(self, mina_code: str) -> MinaJob | None: ...
    def find_by_proposal_id(self, proposal_id: str) -> MinaJob | None: ...
    def find_by_manual_intake_id(self, manual_intake_id: str) -> MinaJob | None: ...
    def list_all(self) -> list[MinaJob]: ...
    def append_event(self, event: MinaJobEvent) -> MinaJobEvent: ...
    def list_events(self, job_id: str) -> list[MinaJobEvent]: ...


class InMemoryMinaJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, MinaJob] = {}
        self._by_code: dict[str, str] = {}
        self._by_proposal: dict[str, str] = {}
        self._by_manual_intake: dict[str, str] = {}
        self._events: dict[str, MinaJobEvent] = {}
        self._sequences: dict[int, int] = {}
        self._lock = Lock()

    def _next_identity(self, sequence_year: int) -> tuple[int, str]:
        sequence_number = self._sequences.get(sequence_year, 0) + 1
        self._sequences[sequence_year] = sequence_number
        return sequence_number, f"MINA{sequence_year}/{sequence_number}"

    def _store_new_job(self, job: MinaJob) -> None:
        self._jobs[job.job_id] = job
        self._by_code[job.mina_code.upper()] = job.job_id
        if job.source_proposal_id:
            self._by_proposal[job.source_proposal_id] = job.job_id
        if job.manual_intake_id:
            self._by_manual_intake[job.manual_intake_id] = job.job_id

    def create_for_proposal(
        self,
        *, proposal_id: str, shipment: Shipment, opened_by: str,
        opened_at: datetime, sequence_year: int, lifecycle_version: int,
        job_kind: MinaJobKind, sales_owner: str | None = None,
        operations_owner: str | None = None,
    ) -> tuple[MinaJob, bool]:
        with self._lock:
            existing_id = self._by_proposal.get(proposal_id)
            if existing_id is not None:
                return self._jobs[existing_id], False
            sequence_number, mina_code = self._next_identity(sequence_year)
            job = MinaJob(
                mina_code=mina_code,
                sequence_year=sequence_year,
                sequence_number=sequence_number,
                lifecycle_version=lifecycle_version,
                job_kind=job_kind,
                intake_channel="email",
                source_proposal_id=proposal_id,
                shipment=shipment.model_copy(deep=True),
                sales_owner=sales_owner,
                operations_owner=operations_owner,
                opened_by=opened_by,
                opened_at=opened_at,
                updated_at=opened_at,
            )
            self._store_new_job(job)
            return job, True

    def create_manual(
        self,
        *, manual_intake_id: str, intake_channel: MinaJobIntakeChannel,
        job_kind: MinaJobKind, shipment: Shipment, opened_by: str,
        opened_at: datetime, sequence_year: int, lifecycle_version: int,
        sales_owner: str | None = None, operations_owner: str | None = None,
    ) -> tuple[MinaJob, bool]:
        with self._lock:
            existing_id = self._by_manual_intake.get(manual_intake_id)
            if existing_id is not None:
                return self._jobs[existing_id], False
            sequence_number, mina_code = self._next_identity(sequence_year)
            job = MinaJob(
                mina_code=mina_code,
                sequence_year=sequence_year,
                sequence_number=sequence_number,
                lifecycle_version=lifecycle_version,
                job_kind=job_kind,
                intake_channel=intake_channel,
                manual_intake_id=manual_intake_id,
                shipment=shipment.model_copy(deep=True),
                sales_owner=sales_owner,
                operations_owner=operations_owner,
                opened_by=opened_by,
                opened_at=opened_at,
                updated_at=opened_at,
            )
            self._store_new_job(job)
            return job, True

    def save(self, job: MinaJob) -> MinaJob:
        self._jobs[job.job_id] = job
        self._by_code[job.mina_code.upper()] = job.job_id
        if job.source_proposal_id:
            self._by_proposal[job.source_proposal_id] = job.job_id
        if job.manual_intake_id:
            self._by_manual_intake[job.manual_intake_id] = job.job_id
        return job

    def get(self, job_id: str) -> MinaJob | None:
        return self._jobs.get(job_id)

    def get_by_code(self, mina_code: str) -> MinaJob | None:
        job_id = self._by_code.get(mina_code.strip().upper())
        return None if job_id is None else self._jobs.get(job_id)

    def find_by_proposal_id(self, proposal_id: str) -> MinaJob | None:
        job_id = self._by_proposal.get(proposal_id)
        return None if job_id is None else self._jobs.get(job_id)

    def find_by_manual_intake_id(self, manual_intake_id: str) -> MinaJob | None:
        job_id = self._by_manual_intake.get(manual_intake_id)
        return None if job_id is None else self._jobs.get(job_id)

    def list_all(self) -> list[MinaJob]:
        return sorted(
            self._jobs.values(),
            key=lambda item: (item.sequence_year, item.sequence_number),
        )

    def append_event(self, event: MinaJobEvent) -> MinaJobEvent:
        self._events.setdefault(event.event_id, event)
        return self._events[event.event_id]

    def list_events(self, job_id: str) -> list[MinaJobEvent]:
        return sorted(
            (event for event in self._events.values() if event.job_id == job_id),
            key=lambda item: (item.occurred_at, item.event_id),
        )
