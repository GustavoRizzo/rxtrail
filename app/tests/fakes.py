"""In-memory test doubles for the domain's ports.

FakeLedger enforces the same rules as the on-chain program, so service tests
can exercise refusals without a validator. It is not the source of truth:
tests/localnet runs the same scenarios against the real program.
"""

from dataclasses import replace
from datetime import UTC, datetime

from rxtrail.domain import (
    Dispensation,
    NotRegisteredError,
    Prescription,
    PrescriptionDocument,
    PrescriptionStatus,
    QuantityExceedsRemainingError,
    Receipt,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class FakeLedger:
    def __init__(self, now=lambda: T0):
        self.now = now
        self.prescribers: set[str] = set()
        self.dispensers: set[str] = set()
        self.prescriptions: dict[bytes, Prescription] = {}
        self.dispensed: dict[bytes, list[Dispensation]] = {}
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    def address_of(self, participant):
        return f"addr-{participant}"

    async def initialize(self, professional_authority, health_authority):
        return Receipt("sig-init", "config")

    async def register_prescriber(self, authority, prescriber):
        self.prescribers.add(prescriber)
        return Receipt(f"sig-reg-{prescriber}", f"prescriber-{prescriber}")

    async def register_dispenser(self, authority, dispenser):
        self.dispensers.add(dispenser)
        return Receipt(f"sig-reg-{dispenser}", f"dispenser-{dispenser}")

    async def set_prescriber_status(self, authority, prescriber, status):
        (self.prescribers.add if status == "active" else self.prescribers.discard)(prescriber)
        return Receipt(f"sig-status-{prescriber}", f"prescriber-{prescriber}")

    async def set_dispenser_status(self, authority, dispenser, status):
        (self.dispensers.add if status == "active" else self.dispensers.discard)(dispenser)
        return Receipt(f"sig-status-{dispenser}", f"dispenser-{dispenser}")

    async def issue_prescription(
        self, prescriber, prescription_id, patient_id, document_hash, quantity, expires_at
    ):
        self.calls.append("issue")
        if prescriber not in self.prescribers:
            raise NotRegisteredError(prescriber)
        self.prescriptions[prescription_id] = Prescription(
            id=prescription_id,
            address=f"rx-{prescription_id.hex()[:8]}",
            prescriber=self.address_of(prescriber),
            patient_id=patient_id,
            document_hash=document_hash,
            quantity_granted=quantity,
            quantity_dispensed=0,
            dispensation_count=0,
            issued_at=self.now(),
            expires_at=expires_at,
            status=PrescriptionStatus.ACTIVE,
        )
        self.dispensed[prescription_id] = []
        return Receipt("sig-issue", self.prescriptions[prescription_id].address)

    async def dispense(self, dispenser, prescription_id, quantity):
        self.calls.append("dispense")
        if dispenser not in self.dispensers:
            raise NotRegisteredError(dispenser)
        current = self.prescriptions[prescription_id]
        if quantity > current.remaining:
            raise QuantityExceedsRemainingError("QuantityExceedsRemaining")
        updated = replace(
            current,
            quantity_dispensed=current.quantity_dispensed + quantity,
            dispensation_count=current.dispensation_count + 1,
        )
        self.prescriptions[prescription_id] = updated
        record = Dispensation(
            address=f"{current.address}-{current.dispensation_count}",
            prescription=current.address,
            index=current.dispensation_count,
            dispenser=self.address_of(dispenser),
            quantity=quantity,
            remaining_after=updated.remaining,
            dispensed_at=self.now(),
        )
        self.dispensed[prescription_id].append(record)
        return Receipt(f"sig-dispense-{record.index}", record.address)

    async def prescription(self, prescription_id):
        return self.prescriptions.get(prescription_id)

    async def participant_status(self, role, participant):
        enabled = self.prescribers if role == "prescriber" else self.dispensers
        return "active" if participant in enabled else None

    async def dispensations(self, prescription):
        return list(self.dispensed.get(prescription.id, []))


class FakeVault:
    def __init__(self):
        self.documents: dict[bytes, tuple[bytes, PrescriptionDocument, bytes]] = {}

    async def store(self, prescription_id, patient_id, prescriber, document, salt):
        self.documents[prescription_id] = (patient_id, document, salt)

    async def fetch(self, prescription_id):
        stored = self.documents.get(prescription_id)
        return None if stored is None else (stored[1], stored[2])


class FakePatients:
    def __init__(self):
        self.ids: dict[str, bytes] = {}

    async def patient_id_for(self, document_number, name):
        return self.ids.setdefault(document_number, bytes([len(self.ids) + 1]) * 32)


def a_document(quantity: int = 30, **changes) -> PrescriptionDocument:
    document = PrescriptionDocument(
        medication="Clonazepam 2mg",
        dosage="1 tablet at night",
        instructions="",
        quantity=quantity,
        prescriber_name="Dr. Ana",
        patient_name="Maria Silva",
        issued_on="2026-10-01",
    )
    return replace(document, **changes)
