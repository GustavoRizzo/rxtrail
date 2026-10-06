"""The prescription rules, mirrored from the on-chain program.

THE PROGRAM IS THE AUTHORITY. These checks are a copy of the ones in
program/programs/rxtrail/src/instructions/ (issue_prescription.rs and
dispense.rs). They run before a transaction is built, so users get a clear
message instead of a failed transaction. If a rule changes in Rust, change it
here too: tests/unit/test_rules.py pins the shared behaviour.
"""

from datetime import datetime

from rxtrail.domain import (
    ExpiryInThePastError,
    InvalidQuantityError,
    Prescription,
    PrescriptionExpiredError,
    PrescriptionNotActiveError,
    PrescriptionStatus,
    QuantityExceedsRemainingError,
)


def check_issue(quantity: int, expires_at: datetime, now: datetime) -> None:
    """Mirror of handle_issue_prescription."""
    if quantity <= 0:
        raise InvalidQuantityError("quantity must be greater than zero")
    if expires_at <= now:
        raise ExpiryInThePastError("expiry must be in the future")


def check_dispense(prescription: Prescription, quantity: int, now: datetime) -> None:
    """Mirror of handle_dispense. RN-06: never past the quantity granted."""
    if quantity <= 0:
        raise InvalidQuantityError("quantity must be greater than zero")
    if prescription.status is not PrescriptionStatus.ACTIVE:
        raise PrescriptionNotActiveError("prescription is not active")
    if now >= prescription.expires_at:
        raise PrescriptionExpiredError(
            f"prescription expired on {prescription.expires_at:%Y-%m-%d}"
        )
    if quantity > prescription.remaining:
        raise QuantityExceedsRemainingError(
            f"asked for {quantity}, only {prescription.remaining} of "
            f"{prescription.quantity_granted} remain"
        )
