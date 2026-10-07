"""Entities and errors of the prescription domain."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


def new_id() -> bytes:
    """A random 32-byte id. Never derived from a real-world document."""
    return secrets.token_bytes(32)


class ParticipantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class PrescriptionStatus(StrEnum):
    ACTIVE = "active"


class CatalogStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"  # recalled: nothing new is prescribed or dispensed


class ProductKind(StrEnum):
    """How a product relates to the original drug (Brazil: referência,
    genérico, similar). What the generic-substitution indicators look at."""

    REFERENCE = "reference"
    GENERIC = "generic"
    SIMILAR = "similar"


class Standing(StrEnum):
    """Where a prescription stands for the people using it, at a given moment.

    Derived from on-chain data, never stored: COMPLETED means every unit
    granted was dispensed; EXPIRED means the deadline passed with units left.
    """

    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Prescription:
    """A prescription as recorded on-chain: terms and counters, no personal data."""

    id: bytes
    address: str
    prescriber: str
    medication: str  # address of the catalog medication
    document_hash: bytes
    quantity_granted: int
    quantity_dispensed: int
    dispensation_count: int
    issued_at: datetime
    expires_at: datetime
    status: PrescriptionStatus
    # Address of the product the prescriber locked ("do not substitute"), if any.
    prescribed_product: str | None = None

    @property
    def remaining(self) -> int:
        return self.quantity_granted - self.quantity_dispensed

    def standing(self, now: datetime) -> Standing:
        if self.remaining == 0:
            return Standing.COMPLETED
        if now >= self.expires_at:
            return Standing.EXPIRED
        return Standing.ACTIVE


@dataclass(frozen=True, slots=True)
class Dispensation:
    """One dispensation as recorded on-chain. Never modified after creation."""

    address: str
    prescription: str
    index: int
    dispenser: str
    product: str  # address of the catalog product handed out
    quantity: int
    remaining_after: int
    dispensed_at: datetime


@dataclass(frozen=True, slots=True)
class Medication:
    """A catalog medication as recorded on-chain: only what a rule needs.

    Its name and guidance live in the off-chain catalog (MedicationDetails);
    the identity hash pins which catalog record this one stands for.
    """

    address: str
    id: bytes
    identity_hash: bytes
    status: CatalogStatus
    registered_at: datetime
    status_changed_at: datetime


@dataclass(frozen=True, slots=True)
class Product:
    """A catalog product (one manufacturer's version of a medication), on-chain."""

    address: str
    id: bytes
    medication: str  # address of the medication it is a version of
    identity_hash: bytes
    status: CatalogStatus
    registered_at: datetime
    status_changed_at: datetime


@dataclass(frozen=True, slots=True)
class MedicationDetails:
    """A medication in the off-chain, public catalog.

    Active ingredient, strength and form define it (see catalog.identity_hash)
    and never change; the rest is guidance that may.
    """

    name: str  # e.g. "Clonazepam 2 mg tablet"
    active_ingredient: str
    strength: str
    form: str
    atc_code: str = ""  # WHO therapeutic classification, e.g. N03AE01
    unit: str = "unit"  # what one unit of the granted quantity is: tablet, ampoule...
    regulatory_list: str = ""  # local control list, e.g. B1 in Brazil
    dosage_guidance: str = ""
    usual_max_daily_units: int | None = None
    max_quantity: int | None = None  # regulatory limit per prescription: warns
    max_validity_days: int | None = None


@dataclass(frozen=True, slots=True)
class ProductDetails:
    """A product in the off-chain, public catalog. Every field defines it."""

    medication_id: str  # hex id of the medication it is a version of
    manufacturer: str
    brand_name: str
    kind: ProductKind


@dataclass(frozen=True, slots=True)
class Receipt:
    """A transaction that landed: what a participant signed, and where it went."""

    signature: str
    address: str


@dataclass(frozen=True, slots=True)
class PrescriptionDocument:
    """The full prescription, kept off-chain. Only its salted hash goes on-chain."""

    medication_id: str  # hex id of the catalog medication, also on-chain
    medication: str  # its name when issued, as the prescriber saw it
    dosage: str
    instructions: str
    quantity: int
    prescriber_name: str
    patient_name: str
    issued_on: str  # ISO date, as written on the paper prescription
    locked_product_id: str = ""  # hex id of the locked product; empty: any version


@dataclass(frozen=True, slots=True)
class AuditTrail:
    """Everything needed to verify one prescription, and the verdict."""

    prescription: Prescription
    dispensations: list[Dispensation]
    document_verified: bool | None  # None: the off-chain document is not available here
    medication: Medication | None = None  # None: the prescribed medication was not found
    problems: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.problems

    @property
    def frozen(self) -> bool:
        """The medication was withdrawn: nothing more can be dispensed for now."""
        return self.medication is not None and self.medication.status is CatalogStatus.WITHDRAWN


# ----------------------------------------------------------------- errors ----


class RxTrailError(Exception):
    """Base for every domain error."""


class NotFoundError(RxTrailError):
    pass


# Mirrors of the on-chain program's errors (program/programs/rxtrail/src/error.rs).
# The program is the authority; these let the app explain a refusal, and the
# rules in `rules.py` raise them before a doomed transaction is ever sent.


class NotProfessionalAuthorityError(RxTrailError):
    pass


class NotHealthAuthorityError(RxTrailError):
    pass


class PrescriberNotActiveError(RxTrailError):
    pass


class DispenserNotActiveError(RxTrailError):
    pass


class InvalidQuantityError(RxTrailError):
    pass


class ExpiryInThePastError(RxTrailError):
    pass


class PrescriptionExpiredError(RxTrailError):
    pass


class PrescriptionNotActiveError(RxTrailError):
    pass


class QuantityExceedsRemainingError(RxTrailError):
    pass


class NotCatalogAuthorityError(RxTrailError):
    pass


class MedicationNotActiveError(RxTrailError):
    pass


class ProductNotActiveError(RxTrailError):
    pass


class ProductMedicationMismatchError(RxTrailError):
    pass


class PrescribedProductMismatchError(RxTrailError):
    pass


class NotRegisteredError(RxTrailError):
    """The signer has no participant record on-chain (Anchor: AccountNotInitialized)."""


class TransactionRejectedError(RxTrailError):
    """The chain refused the transaction, for a reason the app does not model.

    The program is the source of truth: any refusal it gives is an error here,
    even one the Python mirror did not foresee. The chain's own message is kept.
    """


class OutcomeUnknownError(RxTrailError):
    """The transaction was sent, but whether it landed could not be confirmed.

    Never treated as success: look the signature up on an explorer.
    """

    def __init__(self, signature: str, reason: str):
        super().__init__(f"{signature} was sent, outcome unknown: {reason}")
        self.signature = signature


class ChainMismatchError(RxTrailError):
    """This database belongs to another chain (another network, or a reset localnet)."""


class LedgerUnavailableError(RxTrailError):
    """The Solana node could not be reached, even after retries."""


PROGRAM_ERRORS: dict[str, type[RxTrailError]] = {
    "NotProfessionalAuthority": NotProfessionalAuthorityError,
    "NotHealthAuthority": NotHealthAuthorityError,
    "PrescriberNotActive": PrescriberNotActiveError,
    "DispenserNotActive": DispenserNotActiveError,
    "InvalidQuantity": InvalidQuantityError,
    "ExpiryInThePast": ExpiryInThePastError,
    "PrescriptionExpired": PrescriptionExpiredError,
    "PrescriptionNotActive": PrescriptionNotActiveError,
    "QuantityExceedsRemaining": QuantityExceedsRemainingError,
    "NotCatalogAuthority": NotCatalogAuthorityError,
    "MedicationNotActive": MedicationNotActiveError,
    "ProductNotActive": ProductNotActiveError,
    "ProductMedicationMismatch": ProductMedicationMismatchError,
    "PrescribedProductMismatch": PrescribedProductMismatchError,
}
