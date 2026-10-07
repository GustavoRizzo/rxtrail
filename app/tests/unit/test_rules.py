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
    PrescriptionExpiredError,
    QuantityExceedsRemainingError,
)
from tests.fakes import T0, a_prescription


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
    rules.check_dispense(a_prescription(granted=30, dispensed=20), 10, T0)


def test_dispensing_past_the_remainder_is_refused():
    with pytest.raises(QuantityExceedsRemainingError, match="only 10 of 30 remain"):
        rules.check_dispense(a_prescription(granted=30, dispensed=20), 11, T0)


def test_a_fully_dispensed_prescription_refuses_even_one():
    with pytest.raises(QuantityExceedsRemainingError):
        rules.check_dispense(a_prescription(granted=30, dispensed=30), 1, T0)


def test_dispensing_zero_is_refused():
    with pytest.raises(InvalidQuantityError):
        rules.check_dispense(a_prescription(), 0, T0)


def test_expiry_is_exclusive():
    # Mirrors `now < expires_at` in dispense.rs: at the expiry instant, refused.
    p = a_prescription(expires_in=timedelta(days=1))
    rules.check_dispense(p, 1, p.expires_at - timedelta(seconds=1))
    with pytest.raises(PrescriptionExpiredError):
        rules.check_dispense(p, 1, p.expires_at)
