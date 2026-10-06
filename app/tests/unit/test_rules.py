"""The Python mirror of the program's rules.

The same scenarios run against the real program in
program/programs/rxtrail/tests/rxtrail.rs; keep the two in step.
"""

from datetime import timedelta

import pytest

from rxtrail import rules
from rxtrail.domain import (
    ExpiryInThePastError,
    InvalidQuantityError,
    Prescription,
    PrescriptionExpiredError,
    PrescriptionStatus,
    QuantityExceedsRemainingError,
)
from tests.fakes import T0


def prescription(granted=30, dispensed=0, expires_in=timedelta(days=30)) -> Prescription:
    return Prescription(
        id=b"\x01" * 32,
        address="rx",
        prescriber="dr",
        patient_id=b"\x02" * 32,
        document_hash=b"\x03" * 32,
        quantity_granted=granted,
        quantity_dispensed=dispensed,
        dispensation_count=0,
        issued_at=T0,
        expires_at=T0 + expires_in,
        status=PrescriptionStatus.ACTIVE,
    )


@pytest.mark.parametrize("quantity", [0, -1])
def test_issue_needs_a_positive_quantity(quantity):
    with pytest.raises(InvalidQuantityError):
        rules.check_issue(quantity, T0 + timedelta(days=1), T0)


@pytest.mark.parametrize("expires_at", [T0, T0 - timedelta(seconds=1)])
def test_issue_needs_a_future_expiry(expires_at):
    with pytest.raises(ExpiryInThePastError):
        rules.check_issue(30, expires_at, T0)


def test_a_valid_issue_passes():
    rules.check_issue(30, T0 + timedelta(seconds=1), T0)


def test_dispensing_up_to_the_remainder_passes():
    rules.check_dispense(prescription(granted=30, dispensed=20), 10, T0)


def test_dispensing_past_the_remainder_is_refused():
    with pytest.raises(QuantityExceedsRemainingError, match="only 10 of 30 remain"):
        rules.check_dispense(prescription(granted=30, dispensed=20), 11, T0)


def test_a_fully_dispensed_prescription_refuses_even_one():
    with pytest.raises(QuantityExceedsRemainingError):
        rules.check_dispense(prescription(granted=30, dispensed=30), 1, T0)


def test_dispensing_zero_is_refused():
    with pytest.raises(InvalidQuantityError):
        rules.check_dispense(prescription(), 0, T0)


def test_expiry_is_exclusive():
    # Mirrors `now < expires_at` in dispense.rs: at the expiry instant, refused.
    p = prescription(expires_in=timedelta(days=1))
    rules.check_dispense(p, 1, p.expires_at - timedelta(seconds=1))
    with pytest.raises(PrescriptionExpiredError):
        rules.check_dispense(p, 1, p.expires_at)
