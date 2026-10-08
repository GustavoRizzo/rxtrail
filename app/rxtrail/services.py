"""Use cases."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rxtrail import catalog, documents, rules
from rxtrail.domain import (
    AuditTrail,
    CatalogStatus,
    Closure,
    ClosureKind,
    ClosureReason,
    Medication,
    MedicationDetails,
    NotFoundError,
    ParticipantStatus,
    Prescription,
    PrescriptionDocument,
    PrescriptionStatus,
    ProductDetails,
    Receipt,
    new_id,
)
from rxtrail.ports import CatalogDirectory, DocumentVault, PatientDirectory, PrescriptionLedger


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class IssuedPrescription:
    prescription_id: bytes
    patient_id: bytes
    document_hash: bytes
    receipt: Receipt


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """A medication or product just registered: its id and the transaction."""

    id: bytes
    identity_hash: bytes
    receipt: Receipt


class RxTrail:
    """The application: every use case, over the four ports."""

    def __init__(
        self,
        ledger: PrescriptionLedger,
        vault: DocumentVault,
        patients: PatientDirectory,
        catalog: CatalogDirectory,
        now: Callable[[], datetime] = _now,
    ):
        self._ledger = ledger
        self._vault = vault
        self._patients = patients
        self._catalog = catalog
        self._now = now

    # -- setup by the authorities ------------------------------------------

    async def enable_prescriber(self, authority: str, prescriber: str) -> Receipt:
        return await self._ledger.register_prescriber(authority, prescriber)

    async def enable_dispenser(self, authority: str, dispenser: str) -> Receipt:
        return await self._ledger.register_dispenser(authority, dispenser)

    async def suspend_prescriber(self, authority: str, prescriber: str) -> Receipt:
        """Stop a prescriber at once: no new prescriptions, and none of theirs
        can be dispensed. The answer to a leaked key or a revoked licence."""
        return await self._ledger.set_prescriber_status(
            authority, prescriber, ParticipantStatus.SUSPENDED
        )

    async def reinstate_prescriber(self, authority: str, prescriber: str) -> Receipt:
        return await self._ledger.set_prescriber_status(
            authority, prescriber, ParticipantStatus.ACTIVE
        )

    async def suspend_dispenser(self, authority: str, dispenser: str) -> Receipt:
        return await self._ledger.set_dispenser_status(
            authority, dispenser, ParticipantStatus.SUSPENDED
        )

    async def reinstate_dispenser(self, authority: str, dispenser: str) -> Receipt:
        return await self._ledger.set_dispenser_status(
            authority, dispenser, ParticipantStatus.ACTIVE
        )

    # -- catalog authority -----------------------------------------------------

    async def register_medication(self, authority: str, details: MedicationDetails) -> CatalogEntry:
        """Off-chain record first (an orphan is harmless), then the on-chain
        record that pins its meaning."""
        medication_id = new_id()
        digest = catalog.identity_hash(details)
        address = self._ledger.medication_address(medication_id)
        await self._catalog.add_medication(medication_id, address, details, digest)
        receipt = await self._ledger.register_medication(authority, medication_id, digest)
        return CatalogEntry(medication_id, digest, receipt)

    async def register_product(self, authority: str, details: ProductDetails) -> CatalogEntry:
        product_id = new_id()
        digest = catalog.identity_hash(details)
        address = self._ledger.product_address(product_id)
        await self._catalog.add_product(product_id, address, details, digest)
        receipt = await self._ledger.register_product(
            authority, product_id, bytes.fromhex(details.medication_id), digest
        )
        return CatalogEntry(product_id, digest, receipt)

    async def withdraw_medication(self, authority: str, medication_id: bytes) -> Receipt:
        """Recall: no new prescriptions, and every existing one is on hold."""
        return await self._ledger.set_medication_status(
            authority, medication_id, CatalogStatus.WITHDRAWN
        )

    async def reinstate_medication(self, authority: str, medication_id: bytes) -> Receipt:
        return await self._ledger.set_medication_status(
            authority, medication_id, CatalogStatus.ACTIVE
        )

    async def withdraw_product(self, authority: str, product_id: bytes) -> Receipt:
        """Recall one product: pharmacies hand out another version instead."""
        return await self._ledger.set_product_status(authority, product_id, CatalogStatus.WITHDRAWN)

    async def reinstate_product(self, authority: str, product_id: bytes) -> Receipt:
        return await self._ledger.set_product_status(authority, product_id, CatalogStatus.ACTIVE)

    # -- prescriber ----------------------------------------------------------

    async def cancel(
        self, prescriber: str, prescription_id: bytes, reason: ClosureReason, note: str = ""
    ) -> Receipt:
        """Void a prescription nobody dispensed yet (RN-04). Final."""
        return await self._close(prescriber, prescription_id, ClosureKind.CANCELLED, reason, note)

    async def stop(
        self, prescriber: str, prescription_id: bytes, reason: ClosureReason, note: str = ""
    ) -> Receipt:
        """Void what remains of a partly dispensed prescription (RN-04b). Final."""
        return await self._close(prescriber, prescription_id, ClosureKind.STOPPED, reason, note)

    async def _close(
        self,
        prescriber: str,
        prescription_id: bytes,
        kind: ClosureKind,
        reason: ClosureReason,
        note: str,
    ) -> Receipt:
        prescription = await self._ledger.prescription(prescription_id)
        if prescription is None:
            raise NotFoundError(f"no prescription {prescription_id.hex()}")
        rules.check_close(prescription, self._ledger.address_of(prescriber), kind, self._now())
        receipt = await self._ledger.close_prescription(prescriber, prescription_id, kind, reason)
        if note.strip():
            await self._vault.record_closure_note(prescription_id, note.strip())
        return receipt

    async def issue(
        self,
        prescriber: str,
        patient_document_number: str,
        document: PrescriptionDocument,
        valid_for: timedelta,
    ) -> IssuedPrescription:
        """Issue a prescription: hash on-chain, document and identity off-chain.

        Nothing about the patient goes on-chain, not even a pseudonym.
        """
        expires_at = self._now() + valid_for
        medication_id = bytes.fromhex(document.medication_id)
        locked_id = bytes.fromhex(document.locked_product_id) or None
        medication = await self._ledger.medication(medication_id)
        locked = await self._ledger.product(locked_id) if locked_id else None
        if locked_id and locked is None:
            raise NotFoundError("no such product in the catalog")
        rules.check_issue(document.quantity, expires_at, self._now(), medication, locked)

        patient_id = await self._patients.patient_id_for(
            patient_document_number, document.patient_name
        )
        prescription_id = new_id()
        salt = documents.new_salt()
        digest = documents.document_hash(document, salt)

        # Off-chain first: if the transaction then fails, an orphan document is
        # harmless; an on-chain hash whose document was lost could never be
        # verified again.
        await self._vault.store(prescription_id, patient_id, prescriber, document, salt)
        receipt = await self._ledger.issue_prescription(
            prescriber,
            prescription_id,
            medication_id,
            digest,
            document.quantity,
            expires_at,
            locked_id,
        )
        return IssuedPrescription(prescription_id, patient_id, digest, receipt)

    # -- dispenser -------------------------------------------------------------

    async def dispense(
        self, dispenser: str, prescription_id: bytes, product_id: bytes, quantity: int
    ) -> Receipt:
        """Check the rules locally for a clear message; the program decides.

        The local check is a double check only. If it passes and the program
        refuses, the program's refusal is raised as is.
        """
        prescription = await self._ledger.prescription(prescription_id)
        if prescription is None:
            raise NotFoundError(f"no prescription {prescription_id.hex()}")
        medication = await self._medication_at(prescription.medication)
        product = await self._ledger.product(product_id)
        rules.check_dispense(prescription, quantity, self._now(), medication, product)
        return await self._ledger.dispense(dispenser, prescription_id, product_id, quantity)

    async def _medication_at(self, address: str) -> Medication | None:
        (entry,) = await self._ledger.catalog_entries([address])
        return entry if isinstance(entry, Medication) else None

    # -- anyone ------------------------------------------------------------------

    async def audit(self, prescription_id: bytes) -> AuditTrail:
        """Rebuild a prescription's history from the chain and cross-check it."""
        prescription = await self._ledger.prescription(prescription_id)
        if prescription is None:
            raise NotFoundError(f"no prescription {prescription_id.hex()}")
        dispensations = list(await self._ledger.dispensations(prescription))

        problems = []
        if len(dispensations) != prescription.dispensation_count:
            problems.append(
                f"{prescription.dispensation_count} dispensations recorded, "
                f"{len(dispensations)} found"
            )
        total = sum(d.quantity for d in dispensations)
        if total != prescription.quantity_dispensed:
            problems.append(
                f"dispensations add up to {total}, counter says {prescription.quantity_dispensed}"
            )
        if total > prescription.quantity_granted:
            problems.append(
                f"{total} dispensed, more than the {prescription.quantity_granted} granted"
            )
        remaining = prescription.quantity_granted
        for d in sorted(dispensations, key=lambda d: d.index):
            remaining -= d.quantity
            if d.remaining_after != remaining:
                problems.append(
                    f"dispensation {d.index} says {d.remaining_after} remain, history says {remaining}"
                )

        closure = await self._ledger.closure(prescription)
        problems.extend(_closure_problems(prescription, closure))

        stored = await self._vault.fetch(prescription_id)
        verified = None
        if stored is not None:
            document, salt = stored
            verified = documents.verify(document, salt, prescription.document_hash)
            if not verified:
                problems.append("off-chain document does not match the on-chain hash")
        medication = await self._medication_at(prescription.medication)
        return AuditTrail(
            prescription,
            dispensations,
            verified,
            problems=problems,
            medication=medication,
            closure=closure,
        )


def _closure_problems(prescription: Prescription, closure: Closure | None) -> list[str]:
    """A closed prescription has exactly one closure that adds up, and vice versa."""
    closed = prescription.status is not PrescriptionStatus.ACTIVE
    if closure is None:
        return [f"status is {prescription.status}, but no closure was found"] if closed else []
    if not closed:
        return ["a closure exists, but the prescription is still active"]
    problems = []
    if closure.kind.value != prescription.status.value:
        problems.append(f"closure says {closure.kind}, status says {prescription.status}")
    if closure.kind is ClosureKind.CANCELLED and prescription.dispensation_count:
        problems.append("cancelled, yet dispensations exist")
    if closure.quantity_dispensed != prescription.quantity_dispensed:
        problems.append(
            f"closure says {closure.quantity_dispensed} dispensed, "
            f"counter says {prescription.quantity_dispensed}"
        )
    if closure.quantity_voided != prescription.remaining:
        problems.append(
            f"closure voided {closure.quantity_voided}, but {prescription.remaining} remain"
        )
    return problems
