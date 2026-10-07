"""The Python mirror of the program's rules.

The same scenarios run against the real program in
program/programs/rxtrail/tests/rxtrail.rs; keep the two in step.
"""

from datetime import timedelta

import pytest

from rxtrail import rules
from rxtrail.domain import (
    CatalogStatus,
    ExpiryInThePastError,
    InvalidQuantityError,
    MedicationNotActiveError,
    PrescribedProductMismatchError,
    PrescriptionExpiredError,
    ProductMedicationMismatchError,
    ProductNotActiveError,
    QuantityExceedsRemainingError,
)
from tests.fakes import (
    GENERIC_ID,
    REFERENCE_ID,
    T0,
    a_medication,
    a_prescription,
    a_product,
    product_address,
)

OTHER_MEDICATION = b"\xa2" * 32


def issue(quantity=30, expires_at=T0 + timedelta(days=1), medication=None, locked=None):
    rules.check_issue(quantity, expires_at, T0, medication or a_medication(), locked)


def dispense(prescription, quantity, now=T0, medication=None, product=None):
    rules.check_dispense(
        prescription, quantity, now, medication or a_medication(), product or a_product()
    )


@pytest.mark.parametrize("quantity", [0, -1])
def test_issue_needs_a_positive_quantity(quantity):
    with pytest.raises(InvalidQuantityError):
        issue(quantity)


@pytest.mark.parametrize("expires_at", [T0, T0 - timedelta(seconds=1)])
def test_issue_needs_a_future_expiry(expires_at):
    with pytest.raises(ExpiryInThePastError):
        issue(expires_at=expires_at)


def test_a_valid_issue_passes():
    issue(expires_at=T0 + timedelta(seconds=1))


def test_a_withdrawn_medication_cannot_be_prescribed():
    with pytest.raises(MedicationNotActiveError):
        issue(medication=a_medication(CatalogStatus.WITHDRAWN))


def test_only_a_version_of_the_medication_can_be_locked():
    issue(locked=a_product())
    with pytest.raises(ProductMedicationMismatchError):
        issue(locked=a_product(of=OTHER_MEDICATION))
    with pytest.raises(ProductNotActiveError):
        issue(locked=a_product(status=CatalogStatus.WITHDRAWN))


def test_dispensing_up_to_the_remainder_passes():
    dispense(a_prescription(granted=30, dispensed=20), 10)


def test_dispensing_past_the_remainder_is_refused():
    with pytest.raises(QuantityExceedsRemainingError, match="only 10 of 30 remain"):
        dispense(a_prescription(granted=30, dispensed=20), 11)


def test_a_fully_dispensed_prescription_refuses_even_one():
    with pytest.raises(QuantityExceedsRemainingError):
        dispense(a_prescription(granted=30, dispensed=30), 1)


def test_dispensing_zero_is_refused():
    with pytest.raises(InvalidQuantityError):
        dispense(a_prescription(), 0)


def test_expiry_is_exclusive():
    # Mirrors `now < expires_at` in dispense.rs: at the expiry instant, refused.
    p = a_prescription(expires_in=timedelta(days=1))
    dispense(p, 1, now=p.expires_at - timedelta(seconds=1))
    with pytest.raises(PrescriptionExpiredError):
        dispense(p, 1, now=p.expires_at)


def test_the_product_must_be_a_version_of_the_prescribed_medication():
    with pytest.raises(ProductMedicationMismatchError):
        dispense(a_prescription(), 1, product=a_product(of=OTHER_MEDICATION))


def test_a_recalled_product_is_refused_and_another_version_passes():
    with pytest.raises(ProductNotActiveError):
        dispense(a_prescription(), 1, product=a_product(status=CatalogStatus.WITHDRAWN))
    dispense(a_prescription(), 1, product=a_product(GENERIC_ID))


def test_a_withdrawn_medication_freezes_the_prescription():
    with pytest.raises(MedicationNotActiveError):
        dispense(a_prescription(), 1, medication=a_medication(CatalogStatus.WITHDRAWN))


def test_a_locked_product_cannot_be_substituted():
    locked = a_prescription(locked=product_address(REFERENCE_ID))
    dispense(locked, 1, product=a_product(REFERENCE_ID))
    with pytest.raises(PrescribedProductMismatchError):
        dispense(locked, 1, product=a_product(GENERIC_ID))


def test_catalog_checks_come_before_the_counters():
    # As in Rust: account constraints run before the handler's checks.
    with pytest.raises(MedicationNotActiveError):
        dispense(a_prescription(), 0, medication=a_medication(CatalogStatus.WITHDRAWN))
