"""In-memory test doubles for the domain's ports.

FakeLedger enforces the same rules as the on-chain program, so service tests
can exercise refusals without a validator. It is not the source of truth:
tests/localnet runs the same scenarios against the real program.

Every FakeLedger starts with one medication in the catalog and two versions
of it: a reference product and a generic.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from rxtrail.domain import (
    AlreadyDispensedError,
    CatalogStatus,
    Closure,
    ClosureKind,
    Dispensation,
    Medication,
    MedicationNotActiveError,
    NothingDispensedError,
    NothingRemainingError,
    NotPrescriptionIssuerError,
    NotRegisteredError,
    PrescribedProductMismatchError,
    Prescription,
    PrescriptionDocument,
    PrescriptionExpiredError,
    PrescriptionNotActiveError,
    PrescriptionStatus,
    Product,
    ProductMedicationMismatchError,
    ProductNotActiveError,
    QuantityExceedsRemainingError,
    Receipt,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

MEDICATION_ID = b"\xa1" * 32
REFERENCE_ID = b"\xb1" * 32
GENERIC_ID = b"\xb2" * 32


def medication_address(medication_id: bytes) -> str:
    return f"med-{medication_id.hex()[:8]}"


def product_address(product_id: bytes) -> str:
    return f"prod-{product_id.hex()[:8]}"


class FakeLedger:
    def __init__(self, now=lambda: T0):
        self.now = now
        self.prescribers: set[str] = set()
        self.dispensers: set[str] = set()
        self.prescriptions: dict[bytes, Prescription] = {}
        self.dispensed: dict[bytes, list[Dispensation]] = {}
        self.catalog: dict[str, Medication | Product] = {}  # by address
        self.closures: dict[str, Closure] = {}  # by prescription address
        self.calls: list[str] = []
        self._add_medication(MEDICATION_ID, b"\x00" * 32)
        self._add_product(REFERENCE_ID, MEDICATION_ID, b"\x00" * 32)
        self._add_product(GENERIC_ID, MEDICATION_ID, b"\x00" * 32)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    def address_of(self, participant):
        return f"addr-{participant}"

    async def initialize(self, professional_authority, health_authority, catalog_authority):
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

    # -- catalog ----------------------------------------------------------------

    def medication_address(self, medication_id):
        return medication_address(medication_id)

    def product_address(self, product_id):
        return product_address(product_id)

    def _add_medication(self, medication_id, identity_hash):
        address = medication_address(medication_id)
        self.catalog[address] = Medication(
            address, medication_id, identity_hash, CatalogStatus.ACTIVE, self.now(), self.now()
        )
        return address

    def _add_product(self, product_id, medication_id, identity_hash):
        address = product_address(product_id)
        self.catalog[address] = Product(
            address,
            product_id,
            medication_address(medication_id),
            identity_hash,
            CatalogStatus.ACTIVE,
            self.now(),
            self.now(),
        )
        return address

    async def register_medication(self, authority, medication_id, identity_hash):
        self.calls.append("register_medication")
        return Receipt("sig-med", self._add_medication(medication_id, identity_hash))

    async def register_product(self, authority, product_id, medication_id, identity_hash):
        self.calls.append("register_product")
        return Receipt("sig-prod", self._add_product(product_id, medication_id, identity_hash))

    def _set_status(self, address, status):
        self.catalog[address] = replace(self.catalog[address], status=status)
        return Receipt(f"sig-status-{address}", address)

    async def set_medication_status(self, authority, medication_id, status):
        return self._set_status(medication_address(medication_id), status)

    async def set_product_status(self, authority, product_id, status):
        return self._set_status(product_address(product_id), status)

    async def medication(self, medication_id):
        return self.catalog.get(medication_address(medication_id))

    async def product(self, product_id):
        return self.catalog.get(product_address(product_id))

    async def catalog_entries(self, addresses):
        return [self.catalog.get(a) for a in addresses]

    # -- prescriptions ----------------------------------------------------------

    async def issue_prescription(
        self,
        prescriber,
        prescription_id,
        medication_id,
        document_hash,
        quantity,
        expires_at,
        locked_product_id=None,
    ):
        self.calls.append("issue")
        if prescriber not in self.prescribers:
            raise NotRegisteredError(prescriber)
        medication = self.catalog[medication_address(medication_id)]
        if medication.status != CatalogStatus.ACTIVE:
            raise MedicationNotActiveError("MedicationNotActive")
        locked = locked_product_id and product_address(locked_product_id)
        self.prescriptions[prescription_id] = Prescription(
            id=prescription_id,
            address=f"rx-{prescription_id.hex()[:8]}",
            prescriber=self.address_of(prescriber),
            medication=medication.address,
            document_hash=document_hash,
            quantity_granted=quantity,
            quantity_dispensed=0,
            dispensation_count=0,
            issued_at=self.now(),
            expires_at=expires_at,
            status=PrescriptionStatus.ACTIVE,
            prescribed_product=locked or None,
        )
        self.dispensed[prescription_id] = []
        return Receipt("sig-issue", self.prescriptions[prescription_id].address)

    async def dispense(self, dispenser, prescription_id, product_id, quantity):
        self.calls.append("dispense")
        if dispenser not in self.dispensers:
            raise NotRegisteredError(dispenser)
        current = self.prescriptions[prescription_id]
        product = self.catalog[product_address(product_id)]
        if self.catalog[current.medication].status != CatalogStatus.ACTIVE:
            raise MedicationNotActiveError("MedicationNotActive")
        if product.medication != current.medication:
            raise ProductMedicationMismatchError("ProductMedicationMismatch")
        if product.status != CatalogStatus.ACTIVE:
            raise ProductNotActiveError("ProductNotActive")
        if current.prescribed_product not in (None, product.address):
            raise PrescribedProductMismatchError("PrescribedProductMismatch")
        if current.status != PrescriptionStatus.ACTIVE:
            raise PrescriptionNotActiveError("PrescriptionNotActive")
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
            product=product.address,
            quantity=quantity,
            remaining_after=updated.remaining,
            dispensed_at=self.now(),
        )
        self.dispensed[prescription_id].append(record)
        return Receipt(f"sig-dispense-{record.index}", record.address)

    async def close_prescription(self, prescriber, prescription_id, kind, reason):
        self.calls.append(kind.value)
        current = self.prescriptions[prescription_id]
        if current.prescriber != self.address_of(prescriber):
            raise NotPrescriptionIssuerError("NotPrescriptionIssuer")
        if current.status != PrescriptionStatus.ACTIVE:
            raise PrescriptionNotActiveError("PrescriptionNotActive")
        if self.now() >= current.expires_at:
            raise PrescriptionExpiredError("PrescriptionExpired")
        if kind is ClosureKind.CANCELLED and current.dispensation_count:
            raise AlreadyDispensedError("AlreadyDispensed")
        if kind is ClosureKind.STOPPED and not current.dispensation_count:
            raise NothingDispensedError("NothingDispensed")
        if kind is ClosureKind.STOPPED and not current.remaining:
            raise NothingRemainingError("NothingRemaining")
        self.prescriptions[prescription_id] = replace(
            current, status=PrescriptionStatus(kind.value)
        )
        closure = Closure(
            address=f"{current.address}-closure",
            prescription=current.address,
            prescriber=current.prescriber,
            kind=kind,
            reason=reason,
            quantity_dispensed=current.quantity_dispensed,
            quantity_voided=current.remaining,
            closed_at=self.now(),
        )
        self.closures[current.address] = closure
        return Receipt(f"sig-{kind.value}", closure.address)

    async def closure(self, prescription):
        return self.closures.get(prescription.address)

    async def prescription(self, prescription_id):
        return self.prescriptions.get(prescription_id)

    async def prescriptions_by_id(self, ids):
        return [self.prescriptions.get(i) for i in ids]

    async def participant_status(self, role, participant):
        enabled = self.prescribers if role == "prescriber" else self.dispensers
        return "active" if participant in enabled else None

    async def dispensations(self, prescription):
        return list(self.dispensed.get(prescription.id, []))

    async def all_prescriptions(self):
        return list(self.prescriptions.values())

    async def all_dispensations(self):
        return [d for found in self.dispensed.values() for d in found]

    async def all_closures(self):
        return list(self.closures.values())


class FakeVault:
    def __init__(self):
        self.documents: dict[bytes, tuple[bytes, PrescriptionDocument, bytes]] = {}
        self.notes: dict[bytes, str] = {}

    async def store(self, prescription_id, patient_id, prescriber, document, salt):
        self.documents[prescription_id] = (patient_id, document, salt)

    async def fetch(self, prescription_id):
        stored = self.documents.get(prescription_id)
        return None if stored is None else (stored[1], stored[2])

    async def record_closure_note(self, prescription_id, note):
        self.notes[prescription_id] = note


class FakePatients:
    def __init__(self):
        self.ids: dict[str, bytes] = {}

    async def patient_id_for(self, document_number, name):
        return self.ids.setdefault(document_number, bytes([len(self.ids) + 1]) * 32)


class FakeCatalog:
    def __init__(self):
        self.medications: dict[bytes, tuple[str, object, bytes]] = {}
        self.products: dict[bytes, tuple[str, object, bytes]] = {}

    async def add_medication(self, medication_id, address, details, identity_hash):
        self.medications[medication_id] = (address, details, identity_hash)

    async def add_product(self, product_id, address, details, identity_hash):
        self.products[product_id] = (address, details, identity_hash)

    async def medication(self, medication_id):
        stored = self.medications.get(medication_id)
        return None if stored is None else stored[1]


def a_document(quantity: int = 30, **changes) -> PrescriptionDocument:
    document = PrescriptionDocument(
        medication_id=MEDICATION_ID.hex(),
        medication="Clonazepam 2 mg tablet",
        dosage="1 tablet at night",
        instructions="",
        quantity=quantity,
        prescriber_name="Dr. Ana",
        patient_name="Maria Silva",
        issued_on="2026-10-01",
    )
    return replace(document, **changes)


def a_prescription(
    granted=30,
    dispensed=0,
    expires_in=timedelta(days=30),
    locked: str | None = None,
    dispensations: int | None = None,
    status=PrescriptionStatus.ACTIVE,
) -> Prescription:
    return Prescription(
        id=b"\x01" * 32,
        address="rx",
        prescriber="dr",
        medication=medication_address(MEDICATION_ID),
        document_hash=b"\x03" * 32,
        quantity_granted=granted,
        quantity_dispensed=dispensed,
        dispensation_count=(1 if dispensed else 0) if dispensations is None else dispensations,
        issued_at=T0,
        expires_at=T0 + expires_in,
        status=status,
        prescribed_product=locked,
    )


def a_medication(status=CatalogStatus.ACTIVE) -> Medication:
    return Medication(
        medication_address(MEDICATION_ID), MEDICATION_ID, b"\x00" * 32, status, T0, T0
    )


def a_product(product_id=REFERENCE_ID, of=MEDICATION_ID, status=CatalogStatus.ACTIVE) -> Product:
    return Product(
        product_address(product_id),
        product_id,
        medication_address(of),
        b"\x00" * 32,
        status,
        T0,
        T0,
    )
