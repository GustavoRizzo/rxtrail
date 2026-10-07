"""Ports: what the domain needs from the outside world.

Participants are referred to by name (e.g. "dr-ana", "pharmacy-1"). Only the
adapter behind `PrescriptionLedger` turns a name into a signature: private
keys never enter the domain.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, Self

from rxtrail.domain import (
    CatalogStatus,
    Dispensation,
    Medication,
    MedicationDetails,
    ParticipantStatus,
    Prescription,
    PrescriptionDocument,
    Product,
    ProductDetails,
    Receipt,
)


class PrescriptionLedger(Protocol):
    """The on-chain program. Every write is signed by the named participant;
    the operator only pays the fees."""

    async def __aenter__(self) -> Self: ...

    async def __aexit__(self, *exc_info: object) -> None: ...

    def address_of(self, participant: str) -> str: ...

    async def initialize(
        self, professional_authority: str, health_authority: str, catalog_authority: str
    ) -> Receipt: ...

    async def register_prescriber(self, authority: str, prescriber: str) -> Receipt: ...

    async def register_dispenser(self, authority: str, dispenser: str) -> Receipt: ...

    async def set_prescriber_status(
        self, authority: str, prescriber: str, status: ParticipantStatus
    ) -> Receipt: ...

    async def set_dispenser_status(
        self, authority: str, dispenser: str, status: ParticipantStatus
    ) -> Receipt: ...

    # -- catalog: signed by the catalog authority --

    def medication_address(self, medication_id: bytes) -> str: ...

    def product_address(self, product_id: bytes) -> str: ...

    async def register_medication(
        self, authority: str, medication_id: bytes, identity_hash: bytes
    ) -> Receipt: ...

    async def register_product(
        self, authority: str, product_id: bytes, medication_id: bytes, identity_hash: bytes
    ) -> Receipt: ...

    async def set_medication_status(
        self, authority: str, medication_id: bytes, status: CatalogStatus
    ) -> Receipt: ...

    async def set_product_status(
        self, authority: str, product_id: bytes, status: CatalogStatus
    ) -> Receipt: ...

    async def medication(self, medication_id: bytes) -> Medication | None: ...

    async def product(self, product_id: bytes) -> Product | None: ...

    async def catalog_entries(self, addresses: Sequence[str]) -> list[Medication | Product | None]:
        """Many catalog records in one round trip, in the order asked; None if missing."""
        ...

    # -- prescriptions --

    async def issue_prescription(
        self,
        prescriber: str,
        prescription_id: bytes,
        medication_id: bytes,
        document_hash: bytes,
        quantity: int,
        expires_at: datetime,
        locked_product_id: bytes | None = None,
    ) -> Receipt: ...

    async def dispense(
        self, dispenser: str, prescription_id: bytes, product_id: bytes, quantity: int
    ) -> Receipt: ...

    async def prescription(self, prescription_id: bytes) -> Prescription | None: ...

    async def prescriptions_by_id(self, ids: Sequence[bytes]) -> list[Prescription | None]:
        """Many prescriptions in one round trip, in the order asked; None if missing."""
        ...

    async def participant_status(self, role: str, participant: str) -> ParticipantStatus | None:
        """On-chain status of a prescriber or dispenser; None if never enabled."""
        ...

    async def dispensations(self, prescription: Prescription) -> Sequence[Dispensation]: ...


class DocumentVault(Protocol):
    """Off-chain store of prescription documents and their salts."""

    async def store(
        self,
        prescription_id: bytes,
        patient_id: bytes,
        prescriber: str,
        document: PrescriptionDocument,
        salt: bytes,
    ) -> None: ...

    async def fetch(self, prescription_id: bytes) -> tuple[PrescriptionDocument, bytes] | None:
        """(document, salt), or None if this vault does not hold it."""
        ...


class CatalogDirectory(Protocol):
    """Off-chain, public catalog: what each on-chain medication and product is."""

    async def add_medication(
        self, medication_id: bytes, address: str, details: MedicationDetails, identity_hash: bytes
    ) -> None: ...

    async def add_product(
        self, product_id: bytes, address: str, details: ProductDetails, identity_hash: bytes
    ) -> None: ...

    async def medication(self, medication_id: bytes) -> MedicationDetails | None: ...


class PatientDirectory(Protocol):
    """Off-chain link between a patient's real identity and their random id.

    The id never goes on-chain: it only ties a patient's documents together
    in the off-chain store."""

    async def patient_id_for(self, document_number: str, name: str) -> bytes:
        """The patient's random id, created on first sight."""
        ...
