"""The prescription rules, mirrored from the on-chain program.

THE PROGRAM IS THE AUTHORITY. Passing these checks proves nothing: it only
means the transaction is worth sending. Whatever the program then decides is
final, and a refusal is an error even when these checks did not foresee it. These checks are a copy of the ones in
program/programs/rxtrail/src/instructions/ (issue_prescription.rs and
dispense.rs), in the same order. They run before a transaction is built, so
users get a clear message instead of a failed transaction. If a rule changes
in Rust, change it here too: tests/unit/test_rules.py pins the shared behaviour.
"""

from datetime import datetime

from rxtrail.domain import (
    CatalogStatus,
    ExpiryInThePastError,
    InvalidQuantityError,
    Medication,
    MedicationNotActiveError,
    NotFoundError,
    PrescribedProductMismatchError,
    Prescription,
    PrescriptionExpiredError,
    PrescriptionNotActiveError,
    PrescriptionStatus,
    Product,
    ProductMedicationMismatchError,
    ProductNotActiveError,
    QuantityExceedsRemainingError,
)


def _check_catalog(medication: Medication | None, product: Product | None) -> None:
    if medication is None:
        raise NotFoundError("no such medication in the catalog")
    if medication.status is not CatalogStatus.ACTIVE:
        raise MedicationNotActiveError("the medication is withdrawn from the catalog")
    if product is None:
        return
    if product.medication != medication.address:
        raise ProductMedicationMismatchError("the product is not a version of this medication")
    if product.status is not CatalogStatus.ACTIVE:
        raise ProductNotActiveError("the product is withdrawn from the catalog")


def check_issue(
    quantity: int,
    expires_at: datetime,
    now: datetime,
    medication: Medication | None,
    locked_product: Product | None = None,
) -> None:
    """Mirror of IssuePrescription's constraints, then handle_issue_prescription."""
    _check_catalog(medication, locked_product)
    if quantity <= 0:
        raise InvalidQuantityError("quantity must be greater than zero")
    if expires_at <= now:
        raise ExpiryInThePastError("expiry must be in the future")


def check_dispense(
    prescription: Prescription,
    quantity: int,
    now: datetime,
    medication: Medication | None,
    product: Product | None,
) -> None:
    """Mirror of Dispense's constraints, then handle_dispense. RN-06: never
    past the quantity granted."""
    if product is None:
        raise NotFoundError("no such product in the catalog")
    _check_catalog(medication, product)
    if prescription.prescribed_product not in (None, product.address):
        raise PrescribedProductMismatchError(
            "the prescriber locked another product: substitution not allowed"
        )
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
