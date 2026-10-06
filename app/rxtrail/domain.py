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


@dataclass(frozen=True, slots=True)
class Prescription:
    """A prescription as recorded on-chain: terms and counters, no personal data."""

    id: bytes
    address: str
    prescriber: str
    patient_id: bytes
    document_hash: bytes
    quantity_granted: int
    quantity_dispensed: int
    dispensation_count: int
    issued_at: datetime
    expires_at: datetime
    status: PrescriptionStatus

    @property
    def remaining(self) -> int:
        return self.quantity_granted - self.quantity_dispensed


@dataclass(frozen=True, slots=True)
class Dispensation:
    """One dispensation as recorded on-chain. Never modified after creation."""

    address: str
    prescription: str
    index: int
    dispenser: str
    quantity: int
    remaining_after: int
    dispensed_at: datetime


@dataclass(frozen=True, slots=True)
class Receipt:
    """A transaction that landed: what a participant signed, and where it went."""

    signature: str
    address: str


@dataclass(frozen=True, slots=True)
class PrescriptionDocument:
    """The full prescription, kept off-chain. Only its salted hash goes on-chain."""

    medication: str
    dosage: str
    instructions: str
    quantity: int
    prescriber_name: str
    patient_name: str
    issued_on: str  # ISO date, as written on the paper prescription


@dataclass(frozen=True, slots=True)
class AuditTrail:
    """Everything needed to verify one prescription, and the verdict."""

    prescription: Prescription
    dispensations: list[Dispensation]
    document_verified: bool | None  # None: the off-chain document is not available here
    problems: list[str] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.problems


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
}
