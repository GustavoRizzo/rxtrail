"""Use cases."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from rxtrail import documents, rules
from rxtrail.domain import (
    AuditTrail,
    NotFoundError,
    ParticipantStatus,
    PrescriptionDocument,
    Receipt,
    new_id,
)
from rxtrail.ports import DocumentVault, PatientDirectory, PrescriptionLedger


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class IssuedPrescription:
    prescription_id: bytes
    patient_id: bytes
    document_hash: bytes
    receipt: Receipt


class RxTrail:
    """The application: every use case, over the three ports."""

    def __init__(
        self,
        ledger: PrescriptionLedger,
        vault: DocumentVault,
        patients: PatientDirectory,
        now: Callable[[], datetime] = _now,
    ):
        self._ledger = ledger
        self._vault = vault
        self._patients = patients
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

    # -- prescriber ----------------------------------------------------------

    async def issue(
        self,
        prescriber: str,
        patient_document_number: str,
        document: PrescriptionDocument,
        valid_for: timedelta,
    ) -> IssuedPrescription:
        """Issue a prescription: hash on-chain, document and identity off-chain."""
        expires_at = self._now() + valid_for
        rules.check_issue(document.quantity, expires_at, self._now())

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
            prescriber, prescription_id, patient_id, digest, document.quantity, expires_at
        )
        return IssuedPrescription(prescription_id, patient_id, digest, receipt)

    # -- dispenser -------------------------------------------------------------

    async def dispense(self, dispenser: str, prescription_id: bytes, quantity: int) -> Receipt:
        """Check the rules locally for a clear message; the program decides.

        The local check is a double check only. If it passes and the program
        refuses, the program's refusal is raised as is.
        """
        prescription = await self._ledger.prescription(prescription_id)
        if prescription is None:
            raise NotFoundError(f"no prescription {prescription_id.hex()}")
        rules.check_dispense(prescription, quantity, self._now())
        return await self._ledger.dispense(dispenser, prescription_id, quantity)

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

        stored = await self._vault.fetch(prescription_id)
        verified = None
        if stored is not None:
            document, salt = stored
            verified = documents.verify(document, salt, prescription.document_hash)
            if not verified:
                problems.append("off-chain document does not match the on-chain hash")
        return AuditTrail(prescription, dispensations, verified, problems)
