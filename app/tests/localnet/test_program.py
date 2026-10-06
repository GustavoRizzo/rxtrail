"""The full flow against the deployed program: the chain is the authority."""

from datetime import UTC, datetime, timedelta

import pytest

from records.repositories import DjangoDocumentVault, DjangoPatientDirectory
from rxtrail.domain import (
    NotHealthAuthorityError,
    NotRegisteredError,
    QuantityExceedsRemainingError,
    new_id,
)
from rxtrail.services import RxTrail
from tests.fakes import a_document

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
async def enabled(ledger, fresh):
    prescriber, dispenser = fresh("dr"), fresh("pharmacy")
    await ledger.register_prescriber("professional-authority", prescriber)
    await ledger.register_dispenser("health-authority", dispenser)
    return prescriber, dispenser


@pytest.fixture
def app(ledger):
    return RxTrail(ledger, DjangoDocumentVault(), DjangoPatientDirectory())


async def test_issue_dispense_and_audit(app, enabled):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", a_document(quantity=30), timedelta(days=30))

    await app.dispense(dispenser, issued.prescription_id, 20)
    await app.dispense(dispenser, issued.prescription_id, 10)
    trail = await app.audit(issued.prescription_id)

    assert trail.consistent
    assert trail.document_verified is True
    assert trail.prescription.remaining == 0
    assert [d.quantity for d in trail.dispensations] == [20, 10]


async def test_the_program_itself_refuses_over_dispensing(app, ledger, enabled):
    prescriber, dispenser = enabled
    issued = await app.issue(prescriber, "123", a_document(quantity=30), timedelta(days=30))
    await ledger.dispense(dispenser, issued.prescription_id, 25)

    # Straight to the ledger, skipping the Python pre-check: the refusal below
    # comes from the on-chain program, mapped back to the domain error.
    with pytest.raises(QuantityExceedsRemainingError):
        await ledger.dispense(dispenser, issued.prescription_id, 6)
    assert (await ledger.prescription(issued.prescription_id)).quantity_dispensed == 25


async def test_an_unregistered_dispenser_is_refused_by_the_program(app, ledger, enabled, fresh):
    prescriber, _ = enabled
    issued = await app.issue(prescriber, "123", a_document(), timedelta(days=30))

    with pytest.raises(NotRegisteredError):
        await ledger.dispense(fresh("stranger"), issued.prescription_id, 1)


async def test_the_operator_cannot_issue_in_a_prescribers_name(ledger):
    with pytest.raises(NotRegisteredError):
        await ledger.issue_prescription(
            "operator",
            new_id(),
            new_id(),
            new_id(),
            30,
            datetime.now(UTC) + timedelta(days=1),
        )


async def test_only_the_health_authority_enables_dispensers(ledger, fresh):
    with pytest.raises(NotHealthAuthorityError):
        await ledger.register_dispenser("professional-authority", fresh("pharmacy"))


async def test_a_refusal_the_app_does_not_model_is_still_an_error(ledger, enabled):
    from rxtrail.domain import TransactionRejectedError

    prescriber, _ = enabled
    prescription_id = new_id()
    expires = datetime.now(UTC) + timedelta(days=1)
    await ledger.issue_prescription(prescriber, prescription_id, new_id(), new_id(), 10, expires)

    # Same id again: no Python rule checks this; only the program knows the
    # prescription account already exists, and it refuses.
    with pytest.raises(TransactionRejectedError):
        await ledger.issue_prescription(
            prescriber, prescription_id, new_id(), new_id(), 99, expires
        )
    assert (await ledger.prescription(prescription_id)).quantity_granted == 10
