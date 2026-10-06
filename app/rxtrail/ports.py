"""Ports: what the domain needs from the outside world.

Participants are referred to by name (e.g. "dr-ana", "pharmacy-1"). Only the
adapter behind `PrescriptionLedger` turns a name into a signature: private
keys never enter the domain.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, Self

from rxtrail.domain import (
    Dispensation,
    ParticipantStatus,
    Prescription,
    PrescriptionDocument,
    Receipt,
)


class PrescriptionLedger(Protocol):
    """The on-chain program. Every write is signed by the named participant;
    the operator only pays the fees."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    def address_of(self, participant: str) -> str: ...

    async def initialize(self, professional_authority: str, health_authority: str) -> Receipt: ...

    async def register_prescriber(self, authority: str, prescriber: str) -> Receipt: ...

    async def register_dispenser(self, authority: str, dispenser: str) -> Receipt: ...

    async def set_prescriber_status(
        self, authority: str, prescriber: str, status: ParticipantStatus
    ) -> Receipt: ...

    async def set_dispenser_status(
        self, authority: str, dispenser: str, status: ParticipantStatus
    ) -> Receipt: ...

    async def issue_prescription(
        self,
        prescriber: str,
        prescription_id: bytes,
        patient_id: bytes,
        document_hash: bytes,
        quantity: int,
        expires_at: datetime,
    ) -> Receipt: ...

    async def dispense(self, dispenser: str, prescription_id: bytes, quantity: int) -> Receipt: ...

    async def prescription(self, prescription_id: bytes) -> Prescription | None: ...

    async def dispensations(self, prescription: Prescription) -> Sequence[Dispensation]: ...


class DocumentVault(Protocol):
    """Off-chain store of prescription documents and their salts."""

    async def store(
        self,
        prescription_id: bytes,
        patient_id: bytes,
        document: PrescriptionDocument,
        salt: bytes,
    ) -> None: ...

    async def fetch(self, prescription_id: bytes) -> tuple[PrescriptionDocument, bytes] | None:
        """(document, salt), or None if this vault does not hold it."""
        ...


class PatientDirectory(Protocol):
    """Off-chain link between a patient's real identity and their random id."""

    async def patient_id_for(self, document_number: str, name: str) -> bytes:
        """The patient's random id, created on first sight."""
        ...
