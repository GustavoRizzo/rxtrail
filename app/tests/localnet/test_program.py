"""The full flow against the deployed program: the chain is the authority."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest

from records.repositories import DjangoCatalog, DjangoDocumentVault, DjangoPatientDirectory
from rxtrail import catalog
from rxtrail.domain import (
    AlreadyDispensedError,
    ClosureKind,
    ClosureReason,
    MedicationDetails,
    MedicationNotActiveError,
    NotCatalogAuthorityError,
    NotHealthAuthorityError,
    NotPrescriptionIssuerError,
    NotRegisteredError,
    PrescribedProductMismatchError,
    PrescriptionNotActiveError,
    PrescriptionStatus,
    ProductDetails,
    ProductKind,
    ProductMedicationMismatchError,
    ProductNotActiveError,
    QuantityExceedsRemainingError,
    new_id,
)
from rxtrail.services import RxTrail
from tests.fakes import a_document

pytestmark = pytest.mark.django_db(transaction=True)

CATALOG = "catalog-authority"
CLONAZEPAM = MedicationDetails("Clonazepam 2 mg tablet", "clonazepam", "2 mg", "tablet")


@dataclass(frozen=True)
class Stock:
    medication: bytes
    reference: bytes
    generic: bytes


@pytest.fixture
async def enabled(ledger, fresh):
    prescriber, dispenser = fresh("dr"), fresh("pharmacy")
    await ledger.register_prescriber("professional-authority", prescriber)
    await ledger.register_dispenser("health-authority", dispenser)
    return prescriber, dispenser


@pytest.fixture
def app(ledger):
    return RxTrail(ledger, DjangoDocumentVault(), DjangoPatientDirectory(), DjangoCatalog())


async def register(app, details=CLONAZEPAM) -> Stock:
    """A fresh medication (unique per test) with a reference and a generic product."""
    medication = await app.register_medication(
        CATALOG, replace(details, strength=f"{new_id().hex()[:6]} mg")
    )
    versions = []
    for brand, kind in [("Calmazen", ProductKind.REFERENCE), ("Clona Beta", ProductKind.GENERIC)]:
        details = ProductDetails(medication.id.hex(), "Acme Pharma", brand, kind)
        versions.append((await app.register_product(CATALOG, details)).id)
    return Stock(medication.id, *versions)


@pytest.fixture
async def stock(app):
    return await register(app)


def document(stock, **changes):
    return a_document(medication_id=stock.medication.hex(), **changes)


async def test_issue_dispense_and_audit(app, enabled, stock):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", document(stock, quantity=30), timedelta(days=30))

    await app.dispense(dispenser, issued.prescription_id, stock.reference, 20)
    await app.dispense(dispenser, issued.prescription_id, stock.reference, 10)
    trail = await app.audit(issued.prescription_id)

    assert trail.consistent
    assert trail.document_verified is True
    assert trail.prescription.remaining == 0
    assert [d.quantity for d in trail.dispensations] == [20, 10]


async def test_prescriptions_are_read_in_one_call_in_the_order_asked(app, ledger, enabled, stock):
    prescriber, _ = enabled
    first = await app.issue(prescriber, "123", document(stock, quantity=5), timedelta(days=30))
    second = await app.issue(prescriber, "456", document(stock, quantity=7), timedelta(days=30))

    found = await ledger.prescriptions_by_id(
        [second.prescription_id, new_id(), first.prescription_id]
    )

    assert [rx and rx.quantity_granted for rx in found] == [7, None, 5]


async def test_the_program_itself_refuses_over_dispensing(app, ledger, enabled, stock):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", document(stock, quantity=30), timedelta(days=30))
    await ledger.dispense(dispenser, issued.prescription_id, stock.reference, 25)

    # Straight to the ledger, skipping the Python pre-check: the refusal below
    # comes from the on-chain program, mapped back to the domain error.
    with pytest.raises(QuantityExceedsRemainingError):
        await ledger.dispense(dispenser, issued.prescription_id, stock.reference, 6)
    assert (await ledger.prescription(issued.prescription_id)).quantity_dispensed == 25


async def test_an_unregistered_dispenser_is_refused_by_the_program(
    app, ledger, enabled, fresh, stock
):
    prescriber, _ = enabled
    issued = await app.issue(prescriber, "123", document(stock), timedelta(days=30))

    with pytest.raises(NotRegisteredError):
        await ledger.dispense(fresh("stranger"), issued.prescription_id, stock.reference, 1)


async def test_the_operator_cannot_issue_in_a_prescribers_name(ledger, stock):
    with pytest.raises(NotRegisteredError):
        await ledger.issue_prescription(
            "operator",
            new_id(),
            stock.medication,
            new_id(),
            30,
            datetime.now(UTC) + timedelta(days=1),
        )


async def test_only_the_health_authority_enables_dispensers(ledger, fresh):
    with pytest.raises(NotHealthAuthorityError):
        await ledger.register_dispenser("professional-authority", fresh("pharmacy"))


async def test_a_refusal_the_app_does_not_model_is_still_an_error(ledger, enabled, stock):
    from rxtrail.domain import TransactionRejectedError

    prescriber, _ = enabled
    prescription_id = new_id()
    expires = datetime.now(UTC) + timedelta(days=1)
    await ledger.issue_prescription(
        prescriber, prescription_id, stock.medication, new_id(), 10, expires
    )

    # Same id again: no Python rule checks this; only the program knows the
    # prescription account already exists, and it refuses.
    with pytest.raises(TransactionRejectedError):
        await ledger.issue_prescription(
            prescriber, prescription_id, stock.medication, new_id(), 99, expires
        )
    assert (await ledger.prescription(prescription_id)).quantity_granted == 10


async def test_suspending_a_prescriber_freezes_their_prescriptions(app, ledger, enabled, stock):
    from rxtrail.domain import PrescriberNotActiveError

    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", document(stock, quantity=30), timedelta(days=30))
    await app.dispense(dispenser, issued.prescription_id, stock.reference, 10)

    await app.suspend_prescriber("professional-authority", prescriber)
    with pytest.raises(PrescriberNotActiveError):
        await ledger.dispense(dispenser, issued.prescription_id, stock.reference, 5)

    await app.reinstate_prescriber("professional-authority", prescriber)
    await app.dispense(dispenser, issued.prescription_id, stock.reference, 5)
    assert (await ledger.prescription(issued.prescription_id)).quantity_dispensed == 15


async def test_the_catalog_record_pins_its_identity_hash_on_chain(app, ledger, stock):
    on_chain = await ledger.medication(stock.medication)
    details = await DjangoCatalog().medication(stock.medication)

    assert on_chain.identity_hash == catalog.identity_hash(details)
    assert (await ledger.product(stock.generic)).medication == on_chain.address


async def test_only_the_catalog_authority_registers(ledger):
    with pytest.raises(NotCatalogAuthorityError):
        await ledger.register_medication("health-authority", new_id(), new_id())


async def test_the_program_refuses_a_product_of_another_medication(app, ledger, enabled, stock):
    prescriber, dispenser = enabled
    other = await register(app)
    issued = await app.issue(prescriber, "123", document(stock), timedelta(days=30))

    with pytest.raises(ProductMedicationMismatchError):
        await ledger.dispense(dispenser, issued.prescription_id, other.reference, 1)
    trail = await app.audit(issued.prescription_id)
    assert trail.prescription.medication == ledger.medication_address(stock.medication)


async def test_a_product_recall_sends_pharmacies_to_another_version(app, ledger, enabled, stock):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", document(stock), timedelta(days=30))

    await app.withdraw_product(CATALOG, stock.reference)
    with pytest.raises(ProductNotActiveError):
        await ledger.dispense(dispenser, issued.prescription_id, stock.reference, 1)
    await app.dispense(dispenser, issued.prescription_id, stock.generic, 1)

    (dispensation,) = (await app.audit(issued.prescription_id)).dispensations
    assert dispensation.product == ledger.product_address(stock.generic)


async def test_withdrawing_a_medication_freezes_its_prescriptions(app, ledger, enabled, stock):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", document(stock, quantity=30), timedelta(days=30))
    await app.dispense(dispenser, issued.prescription_id, stock.reference, 10)

    await app.withdraw_medication(CATALOG, stock.medication)
    with pytest.raises(MedicationNotActiveError):
        await ledger.dispense(dispenser, issued.prescription_id, stock.generic, 5)
    with pytest.raises(MedicationNotActiveError):
        await ledger.issue_prescription(
            prescriber, new_id(), stock.medication, new_id(), 1, datetime.now(UTC) + timedelta(1)
        )
    assert (await app.audit(issued.prescription_id)).frozen

    await app.reinstate_medication(CATALOG, stock.medication)
    await app.dispense(dispenser, issued.prescription_id, stock.generic, 5)
    assert (await ledger.prescription(issued.prescription_id)).quantity_dispensed == 15


async def test_the_program_keeps_a_locked_brand(app, ledger, enabled, stock):
    prescriber, dispenser = enabled
    locked = document(stock, locked_product_id=stock.reference.hex())
    issued = await app.issue(prescriber, "123", locked, timedelta(days=30))

    with pytest.raises(PrescribedProductMismatchError):
        await ledger.dispense(dispenser, issued.prescription_id, stock.generic, 1)
    await ledger.dispense(dispenser, issued.prescription_id, stock.reference, 1)
    prescription = await ledger.prescription(issued.prescription_id)
    assert prescription.prescribed_product == ledger.product_address(stock.reference)


async def test_cancel_and_stop_end_to_end(app, ledger, enabled, stock):
    prescriber, dispenser = enabled
    untouched = await app.issue(prescriber, "123", document(stock), timedelta(days=30))
    partial = await app.issue(prescriber, "123", document(stock), timedelta(days=30))
    await app.dispense(dispenser, partial.prescription_id, stock.generic, 10)

    await app.cancel(prescriber, untouched.prescription_id, ClosureReason.ISSUED_IN_ERROR, "typo")
    await app.stop(prescriber, partial.prescription_id, ClosureReason.SUSPECTED_MISUSE)

    cancelled = await app.audit(untouched.prescription_id)
    stopped = await app.audit(partial.prescription_id)
    assert cancelled.consistent and stopped.consistent, cancelled.problems + stopped.problems
    assert cancelled.prescription.status is PrescriptionStatus.CANCELLED
    assert (cancelled.closure.kind, cancelled.closure.quantity_voided) == (
        ClosureKind.CANCELLED,
        30,
    )
    assert stopped.closure.reason is ClosureReason.SUSPECTED_MISUSE
    assert (stopped.closure.quantity_dispensed, stopped.closure.quantity_voided) == (10, 20)
    with pytest.raises(PrescriptionNotActiveError):
        await ledger.dispense(dispenser, partial.prescription_id, stock.generic, 1)


async def test_the_program_itself_refuses_to_cancel_a_dispensed_prescription(
    app, ledger, enabled, stock
):
    """Straight to the ledger, past the Python mirror: the chain says no."""
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", document(stock), timedelta(days=30))
    await app.dispense(dispenser, issued.prescription_id, stock.reference, 1)

    with pytest.raises(AlreadyDispensedError):
        await ledger.close_prescription(
            prescriber, issued.prescription_id, ClosureKind.CANCELLED, ClosureReason.OTHER
        )
    assert (await ledger.prescription(issued.prescription_id)).status is PrescriptionStatus.ACTIVE


async def test_another_prescriber_cannot_close_a_prescription(app, ledger, enabled, fresh, stock):
    prescriber, _ = enabled
    other = fresh("dr")
    await ledger.register_prescriber("professional-authority", other)
    issued = await app.issue(prescriber, "123", document(stock), timedelta(days=30))

    with pytest.raises(NotPrescriptionIssuerError):
        await ledger.close_prescription(
            other, issued.prescription_id, ClosureKind.CANCELLED, ClosureReason.OTHER
        )


@pytest.mark.stress
async def test_five_pharmacies_racing_never_exceed_the_grant(app, ledger, fresh, stock):
    """The core promise under real concurrency: 5 pharmacies ask for 10 each,
    at the same time, against a prescription of 30."""
    import asyncio

    prescriber = fresh("dr")
    await ledger.register_prescriber("professional-authority", prescriber)
    pharmacies = [fresh("pharmacy") for _ in range(5)]
    for pharmacy in pharmacies:
        await ledger.register_dispenser("health-authority", pharmacy)
    issued = await app.issue(prescriber, "123", document(stock, quantity=30), timedelta(days=30))

    # Straight to the ledger, all at once: no Python pre-check can serialize them.
    results = await asyncio.gather(
        *(ledger.dispense(p, issued.prescription_id, stock.reference, 10) for p in pharmacies),
        return_exceptions=True,
    )

    landed = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(landed) == 3
    assert len(refused) == 2
    assert all(isinstance(r, QuantityExceedsRemainingError) for r in refused), refused
    trail = await app.audit(issued.prescription_id)
    assert trail.consistent
    assert trail.prescription.quantity_dispensed == 30
    assert len(trail.dispensations) == 3
